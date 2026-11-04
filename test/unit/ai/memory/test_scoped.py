import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai.memory.scope import scope_key
from ai.memory.scoped import ScopedMemories
from ai.memory.scoped_queue import ScopedWriteQueue
from ai.memory.session_scope import session_scopes


class FakeMem0:
    def __init__(self):
        self.items = []
        self.fail_after_add = False
        self.adds = 0

    def get_all(self, filters, limit=200):
        return {'results': [copy.deepcopy(r) for r in self.items if all((r['metadata'].get(k) == v) for k, v in filters.items())][:limit]}

    def search(self, query, filters, limit=5):
        rows = self.get_all(filters, limit)['results']
        for row in rows:
            row['score'] = 1.0 if row['memory'] == query else 0.0
        return {'results': rows}

    def add(self, text, user_id, metadata, infer):
        assert infer is False
        self.adds += 1
        item = {'id': str(self.adds), 'memory': text, 'metadata': {**metadata, 'user_id': user_id}}
        self.items.append(item)
        if self.fail_after_add:
            self.fail_after_add = False
            raise RuntimeError('interrupted after vector add')
        return {'results': [copy.deepcopy(item)]}


def scope(character='a', timeline='daily', timeline_id=''):
    return {'character_id': character, 'timeline': timeline, 'timeline_id': timeline_id}


def metadata(event='one', **kwargs):
    return {'source_app': 'doki', 'session_id': 'chat-a', 'event_id': event, 'occurred_at': '2026-10-30T00:00:00Z', **kwargs}


def test_all_reads_writes_and_tombstones_are_scoped(tmp_path):
    store = ScopedMemories(FakeMem0(), tmp_path / 'events.db')
    spaces = [scope(), scope('b'), scope('a', 'independent', 'scene-1'), scope('a', 'independent', 'scene-2')]
    identities = [store.remember(space, 'same words', metadata())['memory_id'] for space in spaces]
    assert len(set(identities)) == 4
    for space, identity in zip(spaces, identities):
        assert [r['id'] for r in store.listed(space)['memories']] == [identity]
        assert [r['id'] for r in store.search(space, 'same words')['memories']] == [identity]
    with pytest.raises(ValueError):
        store.retire(spaces[1], identities[0])
    store.retire(spaces[0], identities[0])
    assert not store.listed(spaces[0])['memories']
    assert store.listed(spaces[1])['count'] == 1


def test_retries_and_semantic_duplicates_preserve_event_provenance(tmp_path):
    engine = FakeMem0()
    store = ScopedMemories(engine, tmp_path / 'events.db')
    first = store.remember(scope(), 'likes tea', metadata('one', evidence=[{'quote': 'tea'}]))
    assert store.remember(scope(), 'likes tea', metadata('one', evidence=[{'quote': 'tea'}]))['duplicate']
    store.remember(scope(), 'likes tea', metadata('two', source_app='shinsekai'))
    assert engine.adds == 1
    assert len(store.listed(scope())['memories'][0]['sources']) == 2
    with pytest.raises(ValueError):
        store.remember(scope(), 'changed', metadata('one'))
    with pytest.raises(ValueError):
        store.remember(scope(), 'likes tea', metadata('one', evidence=[{'quote': 'changed evidence'}]))
    assert first['memory_id'] == '1'


def test_interrupted_add_recovers_without_second_vector_write(tmp_path):
    engine = FakeMem0()
    engine.fail_after_add = True
    store = ScopedMemories(engine, tmp_path / 'events.db')
    with pytest.raises(RuntimeError):
        store.remember(scope(), 'already curated', metadata())
    assert store.remember(scope(), 'already curated', metadata())['memory_id'] == '1'
    assert engine.adds == 1


def test_revision_keeps_old_vector_and_retires_only_after_confirmation(tmp_path):
    engine = FakeMem0()
    store = ScopedMemories(engine, tmp_path / 'events.db')
    old = store.remember(scope(), 'plan', metadata(status='open'))['memory_id']
    new = store.remember(scope(), 'plan', metadata('revision', status='resolved', supersedes_id=old))['memory_id']
    assert new != old
    assert len(engine.items) == 2
    assert [r['id'] for r in store.listed(scope())['memories']] == [new]


def test_extraction_filters_actual_witnesses_and_caches_output(tmp_path):
    store = ScopedMemories(FakeMem0(), tmp_path / 'events.db')
    seen = []
    def extract(dialogue, name):
        seen.append(dialogue)
        return [{'memory': 'only what A saw'}]
    messages = [
        {'id': '1', 'speaker': 'user', 'text': 'visible', 'witnesses': ['a']},
        {'id': '2', 'text': 'B private', 'witnesses': ['b']},
        {'id': '3', 'text': 'no witness attribution'},
        {'id': '4', 'text': 'shared independent record', 'witnesses': ['a'], 'shared_record': True},
    ]
    store.extract(scope(), messages, metadata(), extract)
    store.extract(scope(), messages, metadata(), extract)
    assert seen == ['user: visible']
    sources = store.listed(scope())['memories'][0]['metadata']['evidence']
    assert [item['message_id'] for item in sources] == ['1']
    with pytest.raises(ValueError):
        store.extract(scope(), [{'text': 'changed', 'witnesses': ['a']}], metadata(), extract)


def test_durable_scoped_queue_survives_disconnect_and_restart(tmp_path):
    path = tmp_path / 'pending.db'
    payload = {'scope': scope('a', 'independent', 'scene'), 'content': 'keep', 'metadata': metadata()}
    first = ScopedWriteQueue(path, request=lambda *_: {'status': 'loading'})
    first.enqueue('remember', payload)
    first.enqueue('remember', payload)
    assert first.flush()['pending'] == 1
    with pytest.raises(ValueError):
        first.enqueue('remember', {**payload, 'content': 'conflict'})
    seen = []
    second = ScopedWriteQueue(path, request=lambda action, body: seen.append((action, body)) or {'ok': True})
    assert second.flush() == {'saved': 1, 'pending': 0}
    assert seen == [('remember', payload)]


def test_history_identity_survives_reload_and_character_rename(tmp_path):
    character = SimpleNamespace(id='stable-a', name='A')
    first, session = session_scopes(tmp_path / 'archive.json', [character])
    character.name = 'Renamed'
    second, reloaded = session_scopes(tmp_path / 'archive/active.json', [character])
    assert session == reloaded
    assert scope_key(first['A']) == scope_key(second['Renamed'])
    third, other = session_scopes(tmp_path / 'another.json', [character])
    assert other != session
    assert third['Renamed']['timeline'] == 'independent'


def test_daily_session_requires_explicit_link_ids(tmp_path):
    directory = tmp_path / 'daily'
    directory.mkdir()
    path = directory / 'memory-scope.json'
    path.write_text(json.dumps({'timeline': 'daily', 'characters': {'native-a': 'linked-a'}}), encoding='utf-8')
    scopes, _ = session_scopes(directory, [SimpleNamespace(id='native-a', name='A')])
    assert scopes['A'] == scope('linked-a')
    with pytest.raises(ValueError):
        session_scopes(directory, [SimpleNamespace(id='native-b', name='B')])


def test_discovered_transport_uses_action_name_and_auth_header(monkeypatch):
    from ai.memory import operations
    monkeypatch.delenv('SHINSEKAI_MEMORY_SERVICE_URL', raising=False)
    monkeypatch.delenv('SHINSEKAI_MEMORY_SERVICE_OWNER', raising=False)
    descriptor = {'url': 'http://127.0.0.1:8787/api/memory', 'token': 'test-token', 'pid': -1}
    with patch('ai.memory.connection.discover', return_value=descriptor), patch('urllib.request.urlopen') as opening:
        opening.return_value.__enter__.return_value.read.return_value = b'{"memories": []}'
        assert operations._memory_service_request('search', {'scope': scope()}) == {'memories': []}
        request = opening.call_args.args[0]
        assert request.full_url.endswith('/api/memory/search')
        assert dict((k.lower(), v) for k, v in request.header_items())['x-shinsekai-bridge-token'] == 'test-token'


def test_builtin_memory_tools_cannot_escape_session_scopes(monkeypatch):
    from ai.memory import operations, session_scope
    monkeypatch.setattr(session_scope, '_runtime_scopes', {'a': scope()})
    monkeypatch.setattr(session_scope, '_active_character', 'a')
    monkeypatch.setattr(session_scope, '_runtime_session', 'scene')
    with patch('ai.memory.scoped.scoped_call', return_value={'ok': True}) as call:
        operations.memory_remember('curated', 'A')
        assert call.call_args.args[1]['scope'] == scope()
        operations.memory_forget('one')
        assert call.call_args.args[0] == 'forget'
        with pytest.raises(ValueError):
            operations.memory_search('private', 'B')


def test_native_hooks_do_not_assign_unattributed_group_messages(tmp_path):
    from ai.memory.hooks import MemoryAutoHooks
    from sdk.hooks import MessageAddedContext
    seen = []
    hooks = MemoryAutoHooks(llm_adapter=None, character_names=['A', 'B'])
    hooks._scopes = {'A': scope('a', 'independent', 'scene'), 'B': scope('b', 'independent', 'scene')}
    hooks._session_id = 'scene'
    hooks._scoped_queue = SimpleNamespace(enqueue=lambda action, body: seen.append(body), flush=lambda: {})
    hooks.message_added(MessageAddedContext(role='user', message={'content': 'unattributed group secret'}, messages=[]))
    hooks.message_added(MessageAddedContext(role='assistant', message={'content': '{"dialog":[{"character_name":"A","text":"visible"}]}', 'witnesses': ['A']}, messages=[{}, {}]))
    hooks.wait_for_idle()
    assert len(seen) == 1
    assert seen[0]['scope']['character_id'] == 'a'
    assert 'unattributed group secret' not in json.dumps(seen)
    assert all(m['witnesses'] == ['a'] for m in seen[0]['messages'])


def test_identical_manual_facts_deduplicate_without_rewriting_user_edits(tmp_path):
    engine = FakeMem0()
    store = ScopedMemories(engine, tmp_path / 'events.db')
    first = store.remember(scope(), 'exact manual fact', metadata('one', edited_by_user=True))
    second = store.remember(scope(), 'exact manual fact', metadata('two', edited_by_user=True))
    assert first['memory_id'] == second['memory_id']
    assert engine.adds == 1
