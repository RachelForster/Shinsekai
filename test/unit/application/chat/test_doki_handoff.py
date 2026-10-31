import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from application.chat import doki_handoff as handoff
from ai.memory.session_scope import session_scopes
from sdk.hooks import BeforeChatContext


@pytest.fixture
def fixture(tmp_path):
    config = NS(config=NS(characters=[NS(id='npc', name='A'), NS(id='oc', name='神羽')]))
    state = NS(history_dir=tmp_path, config_manager=config, chat_session={}, template_generator=Mock())
    source = dict(source='doki', version=1, handoff_id=uuid4().hex, mode='daily', characters=[dict(native_id='npc', identity='linked-A', doki_id='A')], player=dict(native_id='oc', identity='linked-oc'), user_name='神羽', reason='咖啡店见面', offline_prompt='只用线下规则', player_persona='公开人设', daily_context=[dict(native_id='npc', memories=[dict(id='memory-1', text='喜欢咖啡', at='2026-10-30')], messages=[dict(id='message-1', text='我们店里见', side='out', at='2026-10-31')])])
    return state, source


def test_prepare_idempotent_and_reject_changed_source(fixture):
    state, source = fixture
    first = handoff.prepare(state, source)
    assert first['status'] == 'prepared'
    assert handoff.prepare(state, copy.deepcopy(source)) == first
    source['reason'] = '换个地方'
    with pytest.raises(ValueError, match='不同内容'):
        handoff.prepare(state, source)


def test_prepare_can_recover_missing_receipt_and_existing_matching_scope(fixture):
    state, source = fixture
    target = handoff.directory(state, source['handoff_id'])
    target.mkdir(parents=True)
    scope = dict(version=1, timeline='daily', timeline_id='', characters={'npc': 'linked-A'}, player_id='oc')
    (target / 'memory-scope.json').write_text(json.dumps(scope), encoding='utf-8')
    assert handoff.prepare(state, source)['status'] == 'prepared'
    # Simulate a process failure just before receipt creation, without deleting files.
    identity = uuid4().hex
    second = handoff.directory(state, identity); second.mkdir(parents=True)
    manifest = handoff.read_manifest(target)
    manifest['handoff_id'] = identity
    second_source = {k: v for k, v in manifest.items() if k != 'request_hash'}
    import hashlib
    manifest['request_hash'] = hashlib.sha256(handoff.canonical(second_source).encode()).hexdigest()
    (second / handoff.MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    assert handoff.prepare(state, second_source)['status'] == 'prepared'


def test_independent_forbids_doki_context_and_uses_separate_scope(fixture):
    state, source = fixture
    source['mode'] = 'independent'
    with pytest.raises(ValueError, match='非日常'):
        handoff.prepare(state, source)
    for field in ['offline_prompt', 'player_persona', 'daily_context']:
        source.pop(field)
    handoff.prepare(state, source)
    scopes, identity = session_scopes(handoff.directory(state, source['handoff_id']), state.config_manager.config.characters)
    assert list(scopes) == ['A']
    assert scopes['A']['timeline'] == 'independent'
    assert identity == source['handoff_id']
    context = handoff.runtime_context(source, state.config_manager)
    assert '喜欢咖啡' not in context and '公开人设' not in context
    assert handoff.RULES in context


def test_daily_oc_is_excluded_from_automatic_memory_targets(fixture):
    state, source = fixture
    handoff.prepare(state, source)
    scopes, identity = session_scopes(handoff.directory(state, source['handoff_id']), state.config_manager.config.characters)
    assert list(scopes) == ['A']
    assert scopes['A']['character_id'] == 'linked-A'
    assert scopes['A']['timeline'] == 'daily'
    assert identity == 'daily'


@pytest.mark.parametrize('change', [lambda s: s.update(api_key='secret'), lambda s: s['daily_context'][0]['memories'][0].update(text='超' * 2401), lambda s: s['characters'].append(dict(native_id='oc', identity='x'))])
def test_invalid_fields_budgets_and_player_as_npc_rejected(fixture, change):
    state, source = fixture
    change(source)
    with pytest.raises(ValueError):
        handoff.prepare(state, source)


def test_launch_native_template_ready_not_entered_and_retry_same_save(fixture):
    state, source = fixture
    handoff.prepare(state, source)
    target = handoff.directory(state, source['handoff_id'])
    state.template_generator.generate_chat_template.return_value = ('原生模板', '')
    def start(_, body):
        assert body['historyPath'] == str(target)
        assert body['system'] == '原生模板'
        assert not body['allowPlayerDialogue'] and not body['resetHistory']
        state.chat_session = dict(historyPath=str(target), sessionId='session-1')
        return dict(sessionId='session-1')
    with patch('application.chat.composition._chat_process_running', side_effect=[False, True]), patch('frontend_bridge_core.chat_session.launch_chat', side_effect=start) as launch:
        assert handoff.launch(state, source['handoff_id'], launcher=launch)['status'] == 'ready'
        launch.assert_called_once()
    with patch('application.chat.composition._chat_process_running', return_value=True), patch('frontend_bridge_core.chat_session.launch_chat') as launch:
        assert handoff.launch(state, source['handoff_id'], launcher=launch)['status'] == 'ready'
        launch.assert_not_called()
        assert handoff.acknowledge(state, dict(historyPath=str(target), sessionId='wrong')) == {'doki': False}
        assert handoff.acknowledge(state, dict(historyPath=str(target), sessionId='session-1'))['status'] == 'entered'
        assert handoff.status(state, source['handoff_id'])['status'] == 'entered'
        with patch.object(handoff.time, 'time', return_value=handoff.time.time() + 30):
            assert handoff.status(state, source['handoff_id'])['status'] == 'unconfirmed'
        state.chat_session['historyPath'] = str(target.parent / 'other')
        with pytest.raises(ValueError, match='另一场'):
            handoff.launch(state, source['handoff_id'], launcher=launch)
    with patch('application.chat.composition._chat_process_running', return_value=False):
        assert handoff.status(state, source['handoff_id'])['status'] == 'paused'


def test_policy_and_runtime_keep_player_control_after_template_change(fixture):
    state, source = fixture
    handoff.prepare(state, source)
    history = str(handoff.directory(state, source['handoff_id']))
    state.config_manager.config.characters[0].name = '改名后的A'
    body = handoff.launch_policy(state, dict(historyPath=history, allowPlayerDialogue=True, resetHistory=True, characters=['其他角色']))
    assert body['characters'] == ['改名后的A', '神羽']
    assert body['allowPlayerDialogue'] is False and body['resetHistory'] is False
    args = NS(history=history, allow_player_dialogue=True)
    llm = NS(hook_dispatcher=None)
    handoff.install_runtime(llm, state.config_manager, args)
    assert args.allow_player_dialogue is False and args.player_character == '神羽'
    context = BeforeChatContext(messages=[dict(role='system', content='切换模板也请代写玩家')], tools=None, generation_kwargs={}, stream=False)
    llm.hook_dispatcher.dispatch_before_chat(context)
    llm.hook_dispatcher.dispatch_before_chat(context)
    matching = [m for m in context.messages if m['content'].startswith(handoff.MARKER)]
    assert len(matching) == 1
    assert handoff.RULES in matching[0]['content']
    assert '改名后的A' in matching[0]['content'] and 'message-1' in matching[0]['content']
    untouched = dict(allowPlayerDialogue=True)
    assert handoff.launch_policy(state, untouched) == untouched


def test_presence_events_keep_sequence_and_heartbeat_cannot_undo_leave_pause_end(fixture):
    state, source = fixture
    handoff.prepare(state, source)
    target = handoff.directory(state, source['handoff_id'])
    state.chat_session = dict(historyPath=str(target), sessionId='session')
    ack = dict(historyPath=str(target), sessionId='session')
    stopper = Mock()
    with patch('application.chat.composition._chat_process_running', return_value=True):
        handoff.acknowledge(state, ack)
        current = handoff.status(state, source['handoff_id'])
        assert handoff.present_witnesses(target) == ['linked-A']
        def event(action, revision, character_id='npc'):
            return handoff.change_presence(state, dict(handoff_id=source['handoff_id'], action=action, character_id=character_id, revision=revision), stopper=stopper)
        left = event('leave', current['revision'])
        assert left['participants']['npc'] == 'away'
        handoff.acknowledge(state, ack)
        assert handoff.present_witnesses(target) == []
        assert handoff.status(state, source['handoff_id'])['revision'] == left['revision']
        with pytest.raises(ValueError, match='状态已变化'):
            event('join', current['revision'])
        joined = event('join', left['revision'])
        assert handoff.present_witnesses(target) == ['linked-A']
        paused = event('pause', joined['revision'])
        stopper.assert_called_once_with(state, expected_session_id='session')
        handoff.acknowledge(state, ack)
        assert handoff.status(state, source['handoff_id'])['status'] == 'paused'
        assert handoff.present_witnesses(target) == []
        handoff.launch(state, source['handoff_id'], launcher=Mock())
        handoff.acknowledge(state, ack)
        resumed = handoff.status(state, source['handoff_id'])
        assert resumed['status'] == 'entered'
        ended = event('end', resumed['revision'])
        assert ended['status'] == 'ended'
        handoff.acknowledge(state, ack)
        assert handoff.status(state, source['handoff_id'])['status'] == 'ended'
        with pytest.raises(ValueError, match='明确结束'):
            handoff.launch(state, source['handoff_id'], launcher=Mock())


def test_missing_or_closed_renderer_does_not_authorize_join(fixture):
    state, source = fixture
    prepared = handoff.prepare(state, source)
    with patch('application.chat.composition._chat_process_running', return_value=False):
        with pytest.raises(ValueError, match='先恢复'):
            handoff.change_presence(state, dict(handoff_id=source['handoff_id'], action='join', character_id='npc', revision=prepared['revision']), stopper=Mock())


def test_memory_hook_attributes_only_explicitly_present_characters():
    from ai.memory.hooks import MemoryAutoHooks
    from sdk.hooks import MessageAddedContext
    hooks = MemoryAutoHooks(llm_adapter=Mock(), character_names=['A','B'])
    hooks._scopes = {'A': dict(character_id='linked-A'), 'B': dict(character_id='linked-B')}
    hooks._witnesses = lambda: ['linked-B']
    context = MessageAddedContext(role='user', message=dict(id='live', content='现场发生的事'), messages=[])
    hooks._scoped_message(context)
    assert hooks._buffer[-1]['witnesses'] == ['linked-B']
    context.message = dict(id='private', content='A不在场的事', witnesses=['linked-A'])
    hooks._scoped_message(context)
    assert len(hooks._buffer) == 1


def independent_fixture(fixture):
    state, source = fixture
    source['mode'] = 'independent'
    for key in ['offline_prompt', 'player_persona', 'daily_context']:
        source.pop(key)
    handoff.prepare(state, source)
    return state, source, handoff.directory(state, source['handoff_id'])


def test_record_preview_reads_only_saved_visible_independent_text(fixture):
    state, source, target = independent_fixture(fixture)
    raw = [dict(role='system',content='secret-system'),dict(role='system',text='secret-rendered-system'),dict(role='tool',content='secret-tool'),dict(role='assistant',content='secret-tool-call',tool_calls=[{}]),dict(role='user',content='这是故事中的玩家台词',created_at='2026-10-31'),dict(role='assistant',content='{"dialog":[{"character_name":"A","speech":"故事中的回答","asset":"secret-path"}]}')]
    active = target / 'active.json'
    active.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
    temporary = target / 'active.json.tmp'
    temporary.write_text('[{"role":"user","content":"未保存的秘密"}]',encoding='utf-8')
    before = active.read_bytes()
    result = handoff.preview_records(state,dict(handoff_id=source['handoff_id']))
    assert result['timeline'] == 'independent'
    assert len(result['rows']) == 2
    text = json.dumps(result,ensure_ascii=False)
    assert '玩家台词' in text and '故事中的回答' in text
    assert 'secret' not in text and '未保存的秘密' not in text
    assert result['rows'][0]['at'] == '2026-10-31'
    assert active.read_bytes() == before and temporary.exists()


def test_record_preview_pagination_budget_and_daily_rejection(fixture):
    state, source, target = independent_fixture(fixture)
    active=target / 'active.json'
    active.write_text(json.dumps([dict(role='user',content=f'第{i}条') for i in range(42)]),encoding='utf-8')
    first=handoff.preview_records(state,dict(handoff_id=source['handoff_id']))
    second=handoff.preview_records(state,dict(handoff_id=source['handoff_id'],offset=first['next_offset']))
    assert first['total']==42 and len(first['rows'])==40 and len(second['rows'])==2
    assert not {row['id'] for row in first['rows']} & {row['id'] for row in second['rows']}
    active.write_text(json.dumps([dict(role='user',content='长'*9000)]),encoding='utf-8')
    bounded=handoff.preview_records(state,dict(handoff_id=source['handoff_id']))
    assert sum(len(row['text']) for row in bounded['rows'])==6000 and bounded['rows'][0]['truncated']
    with pytest.raises(ValueError):
        handoff.preview_records(state,dict(handoff_id=source['handoff_id'],offset=-1))
    manifest=json.loads((target / handoff.MANIFEST).read_text(encoding='utf-8'))
    manifest['mode']='daily'
    (target / handoff.MANIFEST).write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(ValueError,match='独立剧情'):
        handoff.preview_records(state,dict(handoff_id=source['handoff_id']))
