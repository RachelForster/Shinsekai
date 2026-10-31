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
        assert handoff.launch(state, source['handoff_id'])['status'] == 'ready'
        launch.assert_called_once()
    with patch('application.chat.composition._chat_process_running', return_value=True), patch('frontend_bridge_core.chat_session.launch_chat') as launch:
        assert handoff.launch(state, source['handoff_id'])['status'] == 'ready'
        launch.assert_not_called()
        assert handoff.acknowledge(state, dict(historyPath=str(target), sessionId='wrong')) == {'doki': False}
        assert handoff.acknowledge(state, dict(historyPath=str(target), sessionId='session-1'))['status'] == 'entered'
        assert handoff.status(state, source['handoff_id'])['status'] == 'entered'
        with patch.object(handoff.time, 'time', return_value=handoff.time.time() + 30):
            assert handoff.status(state, source['handoff_id'])['status'] == 'unconfirmed'
        state.chat_session['historyPath'] = str(target.parent / 'other')
        with pytest.raises(ValueError, match='另一场'):
            handoff.launch(state, source['handoff_id'])
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
