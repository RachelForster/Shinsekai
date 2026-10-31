from types import SimpleNamespace as NS
from unittest.mock import patch
import json

import pytest

from ai.memory.scoped import ScopedMemories
from frontend_bridge_core.routes.memory_routes import _daily_memory
from test.unit.ai.memory.test_scoped import FakeMem0


def test_native_editor_reads_and_updates_the_same_scoped_store_as_doki(tmp_path):
    store = ScopedMemories(FakeMem0(), tmp_path / 'events.db')
    scope = {'character_id':'shared-A', 'timeline':'daily', 'timeline_id':''}
    metadata = {'source_app':'doki', 'session_id':'phone', 'event_id':'test-write', 'occurred_at':'2026-10-31T00:00:00Z', 'record_kind':'curated', 'category':'manual', 'status':'stable'}
    store.remember(scope, 'shared memory written from Doki', metadata)
    state = NS(project_root_dir=tmp_path, config_manager=NS(config=NS(characters=[NS(id='native-A',name='A')])))
    request = NS(state=state,body={'name':'A','timeline':'daily'})
    def scoped(_state, action, payload):
        assert payload['scope'] == scope
        if action == 'list': return store.listed(scope)
        if action == 'remember': return store.remember(scope,payload['content'],payload['metadata'])
        if action == 'forget': return store.retire(scope,payload['memoryId'])
        raise AssertionError(action)
    with patch('application.characters.links._request',return_value={'link':{'role':'character','memory_identity':'shared-A'}}), patch('frontend_bridge_core.routes.memory_routes._scoped_memory_operation',side_effect=scoped):
        data = _daily_memory(request,'list').data
        assert data['count'] == 1 and data['memories'][0]['memory'] == 'shared memory written from Doki'
        request.body['content'] = 'added from native editor'
        response = _daily_memory(request,'remember').data
        assert response['count'] == 2
        assert len(store.listed(scope)['memories']) == 2
        request.body['memoryId'] = data['memories'][0]['id']
        assert _daily_memory(request,'forget').data['count'] == 1
    assert store.listed({'character_id':'shared-A','timeline':'independent','timeline_id':'another-save'})['count'] == 0


def test_daily_memory_does_not_fall_back_to_name_or_player_identity(tmp_path):
    state = NS(project_root_dir=tmp_path, config_manager=NS(config=NS(characters=[NS(id='native-A',name='A')])))
    request = NS(state=state,body={'name':'A','timeline':'daily'})
    for link in [None, {'role':'player','memory_identity':'profile'}]:
        with patch('application.characters.links._request',return_value={'link':link}), patch('frontend_bridge_core.routes.memory_routes._scoped_memory_operation') as operation:
            with pytest.raises(ValueError,match='尚未链接'):
                _daily_memory(request,'list')
            operation.assert_not_called()


def test_loading_memory_returns_retryable_error_instead_of_invalid_success_list(tmp_path):
    state = NS(project_root_dir=tmp_path, config_manager=NS(config=NS(characters=[NS(id='native-A',name='A')])))
    request = NS(state=state,body={'name':'A','timeline':'daily'})
    with patch('application.characters.links._request',return_value={'link':{'role':'character','memory_identity':'shared-A'}}), patch('frontend_bridge_core.routes.memory_routes._scoped_memory_operation',return_value={'status':'loading','message':'请直接告诉用户，不要重复调用本工具。'}):
        response = _daily_memory(request,'list')
    assert response.status == 503
    assert response.data['errorCode'] == 'doki_memory_preparing'
    assert '正在准备长期记忆' in response.data['error']
    assert '不要重复调用' not in json.dumps(response.data, ensure_ascii=False)


def test_daily_memory_failure_is_not_reported_as_preparing(tmp_path):
    state = NS(project_root_dir=tmp_path, config_manager=NS(config=NS(characters=[NS(id='native-A',name='A')])))
    request = NS(state=state,body={'name':'A','timeline':'daily'})
    with patch('application.characters.links._request',return_value={'link':{'role':'character','memory_identity':'shared-A'}}), patch('frontend_bridge_core.routes.memory_routes._scoped_memory_operation',return_value={'status':'error','error':'模型加载失败，请重试。'}):
        response = _daily_memory(request,'list')
    assert response.status == 503
    assert response.data['error'] == '模型加载失败，请重试。'
    assert response.data.get('errorCode') != 'doki_memory_preparing'
