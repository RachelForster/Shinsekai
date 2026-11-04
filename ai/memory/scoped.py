"""Scoped Mem0 operations with additive provenance and retry-safe event identities."""
from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from ai.memory.scope import event_key, event_metadata, normalize_scope, scope_key

_lock = threading.RLock()


class ScopedMemories:
    def __init__(self, memory, ledger_path=None):
        self.memory = memory
        self.path = Path(ledger_path or Path.cwd() / 'data/memory/shared_events.db')

    @contextmanager
    def ledger(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from contextlib import closing
        with closing(sqlite3.connect(self.path, timeout=30)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS memory_events (
                  id TEXT PRIMARY KEY, scope TEXT NOT NULL, content_hash TEXT NOT NULL,
                  metadata TEXT NOT NULL, vector_id TEXT, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS extraction_jobs (
                  id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS retired_vectors (
                  scope TEXT NOT NULL, vector_id TEXT NOT NULL, PRIMARY KEY(scope,vector_id));
            ''')
            columns = {r['name'] for r in connection.execute('PRAGMA table_info(extraction_jobs)')}
            if 'input_hash' not in columns:
                connection.execute('ALTER TABLE extraction_jobs ADD COLUMN input_hash TEXT')
            yield connection

    @staticmethod
    def rows(raw):
        return raw.get('results', raw.get('memories', [])) if isinstance(raw, dict) else raw if isinstance(raw, list) else []

    def _query(self, operation, scope, limit, query=None, extra_filters=None):
        method = getattr(self.memory, operation)
        parameters = inspect.signature(method).parameters
        paging = {'top_k' if 'top_k' in parameters else 'limit': max(1, min(int(limit), 10000))}
        filters = {'user_id': scope_key(scope), **(extra_filters or {})}
        raw = method(query, filters=filters, **paging) if query is not None else method(filters=filters, **paging)
        if isinstance(raw, dict) and raw.get('error'):
            raise RuntimeError(str(raw['error']))
        return self.rows(raw)

    def _visible(self, scope, rows):
        with self.ledger() as connection:
            retired = {r['vector_id'] for r in connection.execute('SELECT vector_id FROM retired_vectors WHERE scope=?', [scope_key(scope)])}
            events = connection.execute('SELECT * FROM memory_events WHERE scope=? ORDER BY rowid', [scope_key(scope)]).fetchall()
        provenance = {}
        for event in events:
            provenance.setdefault(event['vector_id'], []).append(json.loads(event['metadata']))
        result = []
        for row in rows:
            identity = str(row.get('id') or '')
            if identity in retired:
                continue
            metadata = dict(row.get('metadata') or {})
            if any(key in metadata and metadata[key] != value for key, value in normalize_scope(scope).items()):
                continue
            sources = provenance.get(identity, [])
            if sources:
                metadata.update(sources[-1])
            result.append({**row, 'metadata': metadata, 'sources': sources})
        return result

    def listed(self, scope, limit=200):
        scope = normalize_scope(scope)
        with _lock:
            rows = self._visible(scope, self._query('get_all', scope, limit))
        return {'scope': scope, 'memories': rows, 'count': len(rows)}

    def search(self, scope, query, limit=5):
        scope = normalize_scope(scope)
        if not str(query).strip():
            return {'scope': scope, 'memories': [], 'count': 0}
        with _lock:
            rows = self._visible(scope, self._query('search', scope, min(int(limit) * 3, 100), str(query)[:6000]))[:max(1, min(int(limit), 30))]
        return {'scope': scope, 'memories': rows, 'count': len(rows)}

    def remember(self, scope, content, metadata):
        scope, metadata = normalize_scope(scope), event_metadata(metadata)
        text = str(content or '').strip()
        if not text or len(text) > 16000:
            raise ValueError('记忆内容为空或过长。')
        identity = event_key(scope, metadata)
        digest = hashlib.sha256(json.dumps([text, metadata], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with _lock, self.ledger() as connection:
            old = connection.execute('SELECT * FROM memory_events WHERE id=?', [identity]).fetchone()
            if old:
                compatible = old['content_hash'] == hashlib.sha256(text.encode()).hexdigest() and json.loads(old['metadata']) == metadata
                if old['content_hash'] != digest and not compatible:
                    raise ValueError('同一记忆事件不能用不同内容或来源重写。')
                return {'ok': True, 'duplicate': True, 'event_id': identity, 'memory_id': old['vector_id']}
            supersedes = metadata.get('supersedes_id')
            if supersedes and not connection.execute('SELECT 1 FROM memory_events WHERE scope=? AND vector_id=?', [scope_key(scope), supersedes]).fetchone():
                raise ValueError('被修正记忆不属于指定角色与时间线。')
            # Recover an add that succeeded immediately before its ledger transaction stopped.
            existing = self._query('get_all', scope, 1, extra_filters={'shared_event_id': identity})
            if existing:
                if (existing[0].get('metadata') or {}).get('shared_content_hash') != digest:
                    raise ValueError('同一事件的已写入内容与本次请求不一致。')
                vector_id = str(existing[0].get('id') or '')
            else:
                from ai.memory.deduplication import find_duplicate_memory
                candidates = self._visible(scope, self._query('search', scope, 5, text))
                candidates = [r for r in candidates if all((r.get('metadata') or {}).get(k, default) == metadata.get(k, default) for k, default in [('category', 'event'), ('status', 'stable'), ('edited_by_user', False)]) and r.get('id') != supersedes]
                duplicate = find_duplicate_memory(text, candidates)
                if duplicate is not None and metadata.get('edited_by_user') and duplicate.match_type != 'exact':
                    duplicate = None
                if duplicate is not None and duplicate.memory_id:
                    vector_id = duplicate.memory_id
                    existing = [{'id': vector_id}]
                else:
                    native_metadata = {**metadata, **scope, 'shared_event_id': identity, 'shared_content_hash': digest}
                    rows = self.rows(self.memory.add(text, user_id=scope_key(scope), metadata=native_metadata, infer=False))
                    vector_id = str(rows[0].get('id') or '') if rows else ''
            if not vector_id:
                raise RuntimeError('记忆引擎未确认写入，保留待重试。')
            connection.execute('INSERT INTO memory_events(id,scope,content_hash,metadata,vector_id) VALUES(?,?,?,?,?)', [identity, scope_key(scope), digest, json.dumps(metadata, ensure_ascii=False), vector_id])
            if supersedes:
                connection.execute('INSERT OR IGNORE INTO retired_vectors VALUES(?,?)', [scope_key(scope), supersedes])
        return {'ok': True, 'duplicate': bool(existing), 'event_id': identity, 'memory_id': vector_id}

    def retire(self, scope, memory_id):
        scope = normalize_scope(scope)
        with _lock, self.ledger() as connection:
            if not connection.execute('SELECT 1 FROM memory_events WHERE scope=? AND vector_id=?', [scope_key(scope), str(memory_id)]).fetchone():
                raise ValueError('该记忆不属于指定角色与时间线。')
            connection.execute('INSERT OR IGNORE INTO retired_vectors VALUES(?,?)', [scope_key(scope), str(memory_id)])
        return {'ok': True, 'memory_id': memory_id}

    def extract(self, scope, messages, metadata, extractor, character_name=''):
        scope, metadata = normalize_scope(scope), event_metadata(metadata)
        if not isinstance(messages, list) or len(messages) > 100 or any(not isinstance(m, dict) for m in messages):
            raise ValueError('提取消息列表无效。')
        visible = [m for m in messages if scope['character_id'] in (m.get('witnesses') or []) and not m.get('shared_record') and not m.get('forwarded_bundle')]
        identity = event_key(scope, metadata)
        digest = hashlib.sha256(json.dumps([visible, metadata], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with _lock:
            with self.ledger() as connection:
                old = connection.execute('SELECT * FROM extraction_jobs WHERE id=?', [identity]).fetchone()
            if old:
                if old['input_hash'] and old['input_hash'] != digest:
                    raise ValueError('同一提取事件不能用不同消息重试。')
                items = json.loads(old['payload'])
            else:
                dialogue = '\n'.join(f"{m.get('speaker') or m.get('side') or ''}: {str(m.get('text') or '')[:6000]}" for m in visible)[-60000:]
                items = extractor(dialogue, character_name or scope['character_id']) if dialogue else []
                if not isinstance(items, list):
                    raise ValueError('记忆提取结果无效。')
                with self.ledger() as connection:
                    connection.execute('INSERT INTO extraction_jobs(id,scope,payload,input_hash) VALUES(?,?,?,?)', [identity, scope_key(scope), json.dumps(items, ensure_ascii=False), digest])
            results = []
            evidence = [{'message_id': m.get('id', ''), 'quote': str(m.get('text') or '')[:800], 'at': m.get('occurred_at', metadata.get('occurred_at', ''))} for m in visible]
            for index, item in enumerate(items):
                text = (item.get('memory') or item.get('text')) if isinstance(item, dict) else str(item)
                if text:
                    results.append(self.remember(scope, text, {**metadata, 'event_id': f"{metadata['event_id']}:{index}", 'record_kind': 'extracted', 'category': 'event', 'status': 'stable', 'evidence': evidence}))
        return {'ok': True, 'count': len(results), 'results': results}


def scoped_call(action, payload, config_manager=None):
    from ai.memory.operations import _memory_service_request
    remote = _memory_service_request(action, payload)
    if remote is not None:
        return remote
    from ai.memory.runtime import ensure_mem0
    store = ScopedMemories(ensure_mem0())
    scope = payload['scope']
    if action == 'list':
        return store.listed(scope, payload.get('limit', 200))
    if action == 'search':
        return store.search(scope, payload.get('query', ''), payload.get('limit', 5))
    if action == 'remember':
        return store.remember(scope, payload.get('content'), payload.get('metadata'))
    if action == 'forget':
        return store.retire(scope, payload.get('memoryId'))
    if action == 'extract':
        from ai.memory.extraction import MemoryExtractor, create_configured_memory_adapter
        from config.config_manager import ConfigManager
        def extract(dialogue, name):
            adapter = create_configured_memory_adapter(config_manager or ConfigManager())
            return MemoryExtractor(adapter).extract_dialogue(dialogue, default_character_name=name, force_character_name=name)[0]
        return store.extract(scope, payload.get('messages', []), payload.get('metadata'), extract, payload.get('characterName', ''))
    raise ValueError('不支持的共享记忆操作。')
