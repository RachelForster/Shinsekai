from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import frontend_bridge


@pytest.mark.parametrize('requested_port', [0, 45123])
def test_run_uses_bound_http_port_for_stream_and_mobile(monkeypatch, tmp_path, requested_port):
    from config import background_manager, character_manager, config_manager
    from ai.llm import template_generator
    from application.runtime import state
    from application.characters import import_recovery
    from frontend_bridge_core import chat_stream
    from frontend_bridge_core.transport import mobile_access
    from ai.memory import connection
    from sdk import logging
    import i18n

    monkeypatch.setenv('EASYAI_PROJECT_ROOT', str(tmp_path))
    monkeypatch.setenv('SHINSEKAI_MEMORY_SERVICE_OWNER', '0')
    monkeypatch.setenv('SHINSEKAI_KNOWLEDGE_SERVICE_OWNER', '0')
    monkeypatch.setattr(frontend_bridge, '_configure_runtime_context', lambda *args: ('', '', str(tmp_path)))
    for name in ('_restart_debug_log', '_install_bridge_signal_handlers', '_start_parent_watchdog', '_set_bridge_state'):
        monkeypatch.setattr(frontend_bridge, name, Mock())
    monkeypatch.setattr(logging, 'configure_logging', Mock())
    monkeypatch.setattr('config.network_proxy.apply_network_proxy_environment_from_system_config', Mock())
    monkeypatch.setattr('config.mirror_env.apply_mirror_environment_from_system_config', Mock())
    monkeypatch.setattr(config_manager, 'ConfigManager', Mock(return_value=SimpleNamespace(config=SimpleNamespace(system_config=SimpleNamespace(ui_language='zh')))))
    monkeypatch.setattr(character_manager, 'CharacterManager', Mock())
    monkeypatch.setattr(background_manager, 'BackgroundManager', Mock())
    monkeypatch.setattr(template_generator, 'TemplateGenerator', Mock())
    monkeypatch.setattr(i18n, 'init_i18n', Mock())
    monkeypatch.setattr(state, 'BridgeState', lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(import_recovery, 'recover_model_imports', Mock())
    bound_port = 57231 if requested_port == 0 else requested_port
    server = Mock(server_address=('127.0.0.1', bound_port))
    http = Mock(return_value=server)
    stream = Mock()
    stream_factory = Mock(return_value=stream)
    mobile = Mock()
    monkeypatch.setattr(frontend_bridge, 'ThreadingHTTPServer', http)
    monkeypatch.setattr(chat_stream, 'ChatStreamService', stream_factory)
    monkeypatch.setattr(mobile_access, 'MobileAccessTransport', mobile)

    class StopStartup(Exception):
        pass

    def publish(url, token, root):
        assert url == f'http://127.0.0.1:{bound_port}'
        raise StopStartup

    monkeypatch.setattr(connection, 'publish_endpoint', publish)
    with pytest.raises(StopStartup):
        frontend_bridge.run('127.0.0.1', requested_port, auth_token='test-only')
    http.assert_called_once()
    assert http.call_args.args[0] == ('127.0.0.1', requested_port)
    assert stream_factory.call_args.kwargs['bridge_port'] == bound_port
    assert mobile.call_args.kwargs['preferred_http_port'] == bound_port + 2
    stream.start.assert_called_once()
