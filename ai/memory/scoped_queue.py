"""Durable scoped requests; concurrent chat processes share SQLite, not JSON snapshots."""
import hashlib
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from ai.memory.scope import event_key, normalize_scope


class ScopedWriteQueue:
    def __init__(self, path=None, request=None):
        self.path = Path(path or Path.cwd() / 'data/memory/pending_scoped.db')
        self.request = request

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,action TEXT,payload TEXT,saved INTEGER DEFAULT 0,error TEXT DEFAULT "")')
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def enqueue(self, action, payload):
        normalize_scope(payload['scope'])
        if action not in {'remember', 'extract'}:
            raise ValueError('不支持的排队操作。')
        identity = action + ':' + event_key(payload['scope'], payload['metadata'])
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self.connection() as connection:
            old = connection.execute('SELECT payload FROM requests WHERE id=?', [identity]).fetchone()
            if old and old['payload'] != serialized:
                raise ValueError('同一事件不能以不同内容排队。')
            connection.execute('INSERT OR IGNORE INTO requests(id,action,payload) VALUES(?,?,?)', [identity, action, serialized])
        return {'ok': True, 'queued': True, 'id': identity}

    def flush(self, limit=20):
        from ai.memory.scoped import scoped_call
        request = self.request or scoped_call
        with self.connection() as connection:
            rows = connection.execute('SELECT * FROM requests WHERE saved=0 ORDER BY rowid LIMIT ?', [limit]).fetchall()
        saved = 0
        for row in rows:
            try:
                result = request(row['action'], json.loads(row['payload']))
                if not isinstance(result, dict) or result.get('ok') is not True:
                    raise RuntimeError(str((result or {}).get('error') or (result or {}).get('status') or '记忆尚未确认写入。'))
                with self.connection() as connection:
                    connection.execute('UPDATE requests SET saved=1,error="" WHERE id=?', [row['id']])
                saved += 1
            except Exception as exc:
                with self.connection() as connection:
                    connection.execute('UPDATE requests SET error=? WHERE id=?', [str(exc)[:1000], row['id']])
        with self.connection() as connection:
            pending = connection.execute('SELECT count(*) FROM requests WHERE saved=0').fetchone()[0]
        return {'saved': saved, 'pending': pending}


def start_worker():
    import logging
    import threading
    import time
    def work():
        queue = ScopedWriteQueue()
        while True:
            time.sleep(10)
            try:
                queue.flush()
            except Exception:
                logging.getLogger(__name__).exception("scoped memory queue remains pending")
    threading.Thread(target=work, name="scoped-memory-recovery", daemon=True).start()
