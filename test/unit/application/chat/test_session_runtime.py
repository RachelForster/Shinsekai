from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat import session_runtime


def test_chat_child_registers_reminders_before_templates_are_loaded(tmp_path, monkeypatch):
    # A fresh interpreter avoids registrations leaked by other tests or the bridge.
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", """
import json
import sys
from types import SimpleNamespace
from application.chat.session_runtime import _import_builtin_tools
from ai.tools.tool_manager import ToolManager
from sdk.tool_registry import apply_registered_tools

assert 'ai.llm.template.integrations.tools' not in sys.modules
_import_builtin_tools()
manager = ToolManager()
# The same one-time registry application performed by plugin startup.
apply_registered_tools(manager)
names = {entry['function']['name'] for entry in manager.get_definitions(groups='default')}
assert 'manage_reminders' in names, names
sys.modules['ai.tools.reminder_tools'].get_llm_host_runtime = lambda: SimpleNamespace(
    manage_reminders=lambda payload: {'ok': True, 'action': payload['action']}
)
assert json.loads(manager.execute('manage_reminders', '{"action":"list"}')) == {
    'ok': True, 'action': 'list'
}
"""],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(autouse=True)
def _reset_active_initialization(monkeypatch):
    monkeypatch.setattr(session_runtime, "_active_initialization", None)


class _Transport:
    def __init__(self, *, streaming: bool) -> None:
        self.streaming = streaming
        self.stream_sink = object() if streaming else None
        self.events = []
        self.initialization_events = []
        self.closed_initialization = 0

    def emit(self, payload) -> None:
        self.events.append(payload)

    def emit_initialization(self, payload) -> None:
        self.initialization_events.append(payload)

    def bind_command_dispatcher(self, dispatcher) -> None:
        self.dispatcher = dispatcher

    def close_initialization(self) -> None:
        self.closed_initialization += 1

    def close(self) -> None:
        pass


class _Initialization:
    service = SimpleNamespace(report=Mock())

    def __init__(self) -> None:
        self.completed = 0

    def phase(self, _name):
        return nullcontext()

    def complete(self) -> None:
        self.completed += 1


def _options(**overrides):
    args = {
        "bg": "room",
        "effect_names": "rain",
        "headless": False,
        "history": "history.json",
        "init_sprite_path": "sprite.png",
        "media_selection_mode": "indexed",
        "room_id": "",
        "stream_endpoint": "ws://chat",
        "template": "default",
        "tts": "none",
        "t2i": "",
        "workflow": "workflow.yaml",
    }
    args.update(overrides)
    return session_runtime.ChatLaunchOptions(
        args=SimpleNamespace(**args),
        config=SimpleNamespace(),
        translate=lambda key, **_kwargs: key,
        translate_bundle=lambda key, _locale, **_kwargs: key,
        create_asr_adapter=Mock(),
        asr_language=lambda _config: "en",
        started_at=0.0,
    )


def _startup(config=None):
    return SimpleNamespace(
        config=config or SimpleNamespace(),
        llm_manager=SimpleNamespace(get_messages=lambda: []),
        tts_manager=None,
        t2i_manager=None,
        plugin_manager=None,
        messages=[],
        character_names=(),
    )


def test_factory_selects_streaming_and_headless_sessions(monkeypatch) -> None:
    monkeypatch.setattr(
        session_runtime,
        "create_chat_startup_context",
        lambda *_args, config, **_kwargs: _startup(config),
    )

    streaming_transport = _Transport(streaming=True)
    streaming = session_runtime.create_chat_session(
        _options(),
        streaming_transport,
    )
    headless_transport = _Transport(streaming=False)
    headless = session_runtime.create_chat_session(
        _options(stream_endpoint="", headless=True),
        headless_transport,
    )

    assert isinstance(streaming, session_runtime.StreamingChatSession)
    assert isinstance(headless, session_runtime.HeadlessChatSession)
    assert streaming_transport.initialization_events[0]["type"] == "chat.init.progress"
    assert headless_transport.initialization_events[0]["type"] == "chat.init.progress"


def test_factory_reports_missing_llm_as_initialization_failure(
    monkeypatch,
    capsys,
) -> None:
    def fail_startup(*_args, **_kwargs):
        raise session_runtime.MissingLlmProviderError("missing llm")

    monkeypatch.setattr(session_runtime, "create_chat_startup_context", fail_startup)
    transport = _Transport(streaming=True)

    with pytest.raises(session_runtime.MissingLlmProviderError):
        session_runtime.create_chat_session(_options(), transport)

    assert transport.initialization_events[-1]["type"] == "chat.init.failed"
    assert transport.closed_initialization == 1
    assert "main.err_select_llm" in capsys.readouterr().out


def test_config_error_is_reported_through_preparsed_transport(monkeypatch) -> None:
    transport = _Transport(streaming=False)
    monkeypatch.setattr(
        "config.network_proxy.apply_network_proxy_environment_from_system_config",
        lambda: None,
    )
    monkeypatch.setattr(
        "config.mirror_env.apply_mirror_environment_from_system_config",
        lambda: None,
    )
    monkeypatch.setattr(session_runtime, "_import_builtin_tools", lambda: None)
    monkeypatch.setattr(
        session_runtime,
        "load_chat_config",
        Mock(side_effect=ValueError("invalid system yaml")),
    )

    with pytest.raises(ValueError, match="invalid system yaml"):
        session_runtime.parse_launch_options(transport)

    failed = transport.initialization_events[-1]
    assert failed["type"] == "chat.init.failed"
    assert failed["task"]["error"] == "invalid system yaml"
    assert failed["task"]["message"] == "Failed while loading configuration."


def test_early_launch_endpoints_prefer_cli_without_consuming_config(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "application.chat.launch_args.peek_chat_launch_endpoints",
        lambda: {
            "init_stream_endpoint": "ws://config-init",
            "stream_endpoint": "ws://config-runtime",
        },
    )
    monkeypatch.setattr(
        session_runtime.sys,
        "argv",
        [
            "main.py",
            "--stream-endpoint=ws://ignored-runtime",
            "--stream-endpoint",
            "ws://cli-runtime",
        ],
    )

    endpoints = session_runtime.peek_launch_endpoints()

    assert endpoints.init_stream_endpoint == "ws://config-init"
    assert endpoints.stream_endpoint == "ws://cli-runtime"


def test_argument_error_is_reported_through_preparsed_transport(monkeypatch) -> None:
    transport = _Transport(streaming=False)
    config = SimpleNamespace(
        config=SimpleNamespace(
            system_config=SimpleNamespace(ui_language="zh_CN"),
        )
    )
    monkeypatch.setattr(
        "config.network_proxy.apply_network_proxy_environment_from_system_config",
        lambda: None,
    )
    monkeypatch.setattr(
        "config.mirror_env.apply_mirror_environment_from_system_config",
        lambda: None,
    )
    monkeypatch.setattr(session_runtime, "_import_builtin_tools", lambda: None)
    monkeypatch.setattr(session_runtime, "load_chat_config", lambda: config)
    monkeypatch.setattr("i18n.init_i18n", lambda _language: None)
    monkeypatch.setattr(
        "application.chat.launch_args.load_chat_launch_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "application.chat.launch_args.parse_chat_args",
        Mock(side_effect=ValueError("invalid launch argument")),
    )

    with pytest.raises(ValueError, match="invalid launch argument"):
        session_runtime.parse_launch_options(transport)

    failed = transport.initialization_events[-1]
    assert failed["type"] == "chat.init.failed"
    assert failed["task"]["error"] == "invalid launch argument"
    assert failed["task"]["message"] == "Failed while reading chat settings."


def test_argparse_system_exit_is_reported_as_failure(monkeypatch) -> None:
    transport = _Transport(streaming=False)
    config = SimpleNamespace(
        config=SimpleNamespace(
            system_config=SimpleNamespace(ui_language="zh_CN"),
        )
    )
    monkeypatch.setattr(
        "config.network_proxy.apply_network_proxy_environment_from_system_config",
        lambda: None,
    )
    monkeypatch.setattr(
        "config.mirror_env.apply_mirror_environment_from_system_config",
        lambda: None,
    )
    monkeypatch.setattr(session_runtime, "_import_builtin_tools", lambda: None)
    monkeypatch.setattr(session_runtime, "load_chat_config", lambda: config)
    monkeypatch.setattr("i18n.init_i18n", lambda _language: None)
    monkeypatch.setattr(
        "application.chat.launch_args.load_chat_launch_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "application.chat.launch_args.parse_chat_args",
        Mock(side_effect=SystemExit(2)),
    )

    with pytest.raises(SystemExit) as raised:
        session_runtime.parse_launch_options(transport)

    assert raised.value.code == 2
    failed = transport.initialization_events[-1]
    assert failed["type"] == "chat.init.failed"
    assert failed["task"]["error"] == "2"
    assert failed["task"]["message"] == "Failed while reading chat settings."


def test_session_factory_reuses_preparse_initialization_service(monkeypatch) -> None:
    transport = _Transport(streaming=True)
    initialization = session_runtime._initialization_for(transport)
    events_before_factory = len(transport.initialization_events)
    monkeypatch.setattr(
        session_runtime,
        "create_chat_startup_context",
        lambda *_args, config, **_kwargs: _startup(config),
    )

    session = session_runtime.create_chat_session(_options(), transport)

    assert session.initialization is initialization
    assert len(transport.initialization_events) == events_before_factory
    assert (
        sum(
            event["task"]["phase"] == "preparing"
            for event in transport.initialization_events
            if event["type"] == "chat.init.progress"
        )
        == 1
    )


def test_headless_session_owns_workflow_and_queue_assembly(monkeypatch) -> None:
    config = SimpleNamespace(
        config=SimpleNamespace(characters=[]),
    )
    options = _options(stream_endpoint="", headless=True, workflow="")
    options = session_runtime.ChatLaunchOptions(
        args=options.args,
        config=config,
        translate=options.translate,
        translate_bundle=options.translate_bundle,
        create_asr_adapter=options.create_asr_adapter,
        asr_language=options.asr_language,
        started_at=options.started_at,
    )
    workflow = SimpleNamespace(start=Mock(), stop=Mock())
    handles = SimpleNamespace(
        input_queue="input",
        dialog_queue="tts",
        presentation_queue="audio",
        ui_worker="ui-worker",
    )
    captured = {}

    def build_workflow(**kwargs):
        captured.update(kwargs)
        return workflow

    monkeypatch.setattr(
        "application.runtime.workflow.build_runtime_workflow",
        build_workflow,
    )
    monkeypatch.setattr(
        "application.runtime.workflow.get_chat_workflow_handles",
        lambda _workflow: handles,
    )
    monkeypatch.setattr(
        "application.chat.presentation.load_presentation_assets",
        lambda *_args: SimpleNamespace(bgm_paths=[], background_sprites=[]),
    )
    monkeypatch.setattr(
        "application.chat.build_effect_context.build_effect_context",
        lambda *_args: SimpleNamespace(keyword_map={"rain": "rain.mp3"}),
    )
    monkeypatch.setattr(
        "core.paths.resource_path",
        lambda path: f"bundled/{path}",
    )
    session = session_runtime.HeadlessChatSession(
        options,
        _startup(config),
        _Transport(streaming=False),
        _Initialization(),
    )

    runtime = session._build_runtime()

    assert captured["workflow_path"].endswith("assets/system/workflow/headless.yaml")
    assert runtime.workflow is workflow
    assert runtime.input_queue == "input"
    assert runtime.dialog_queue == "tts"
    assert runtime.presentation_queue == "audio"
    assert runtime.effect_keyword_map == {"rain": "rain.mp3"}


def test_semantic_mode_injects_lookup_strategy_before_workflow_start(
    monkeypatch,
) -> None:
    character = SimpleNamespace(
        name="Alice",
        sprites=[{"path": "calm.png"}, {"path": "angry.png"}],
        emotion_tags="立绘 1：平静\n立绘 2：愤怒",
    )
    config = SimpleNamespace(
        config=SimpleNamespace(characters=[character]),
        get_character_by_name=lambda name: character if name == "Alice" else None,
    )
    options = _options(media_selection_mode="semantic")
    workflow = SimpleNamespace(start=Mock(), stop=Mock())
    dialog_media_worker = SimpleNamespace(asset_lookup_strategy=None)
    handles = SimpleNamespace(
        input_queue="input",
        dialog_queue="dialog",
        presentation_queue="presentation",
        ui_worker="ui",
        dialog_media_worker=dialog_media_worker,
    )
    strategy = object()
    background = SimpleNamespace(
        name="classroom",
        sprites=[{"path": "day.png"}],
        bg_tags="场景 1：晴朗教室",
        bgm_list=["quiet.mp3"],
        bgm_tags="音乐 1：安静",
    )
    monkeypatch.setattr(
        "application.runtime.workflow.build_runtime_workflow",
        lambda **_kwargs: workflow,
    )
    monkeypatch.setattr(
        "application.runtime.workflow.get_chat_workflow_handles",
        lambda _workflow: handles,
    )
    monkeypatch.setattr(
        "application.chat.presentation.load_presentation_assets",
        lambda *_args: SimpleNamespace(
            bgm_paths=["quiet.mp3"],
            background_sprites=background.sprites,
            background=background,
        ),
    )
    monkeypatch.setattr(
        "application.chat.build_effect_context.build_effect_context",
        lambda *_args: SimpleNamespace(keyword_map={}),
    )
    factory = Mock(return_value=strategy)
    monkeypatch.setattr(
        "application.chat.dialog_media.create_asset_lookup_strategy",
        factory,
    )
    indexer = Mock(return_value={"catalogCount": 3, "assetCount": 4, "addedCount": 4})
    monkeypatch.setattr(
        "ai.memory.media_assets.ensure_media_asset_indexes",
        indexer,
    )
    startup = _startup(config)
    startup.character_names = ("Alice",)
    session = session_runtime.StreamingChatSession(
        options,
        startup,
        _Transport(streaming=True),
        _Initialization(),
    )

    session._build_runtime()

    factory.assert_called_once_with("semantic")
    catalogs = indexer.call_args.args[0]
    assert [catalog.scope for catalog in catalogs] == [
        "sprite:Alice",
        "scene:classroom",
        "bgm:classroom",
    ]
    assert [candidate.tags for candidate in catalogs[0].candidates] == [
        "平静",
        "愤怒",
    ]
    assert dialog_media_worker.asset_lookup_strategy is strategy


def test_install_app_runtime_projects_all_session_dependencies(monkeypatch) -> None:
    config = SimpleNamespace()
    options = _options()
    startup = _startup(config)
    startup.tts_manager = "tts-manager"
    startup.t2i_manager = "t2i-manager"
    initialization = _Initialization()
    session = session_runtime.StreamingChatSession(
        options,
        startup,
        _Transport(streaming=True),
        initialization,
    )
    session.ui_updates = "ui-updates"
    session.chat_turn_service = "turn-service"
    session.runtime = session_runtime._RuntimeComponents(
        workflow=SimpleNamespace(),
        input_queue="input",
        dialog_queue="tts",
        presentation_queue="audio",
        ui_worker="worker",
        presentation_assets=SimpleNamespace(bgm_paths=["bgm.mp3"]),
        effect_keyword_map={"rain": "rain.mp3"},
        text_processor="processor",
        opencc="opencc",
    )
    captured = []
    monkeypatch.setattr("application.runtime.context.set_app_runtime", captured.append)

    session._install_app_runtime()

    runtime = captured[0]
    assert runtime.config is config
    assert runtime.ui_update_manager == "ui-updates"
    assert runtime.llm_manager is startup.llm_manager
    assert runtime.tts_manager == "tts-manager"
    assert runtime.t2i_manager == "t2i-manager"
    assert runtime.bgm_list == ["bgm.mp3"]
    assert runtime.user_input_queue == "input"
    assert runtime.chat_turn_service == "turn-service"


def test_headless_shutdown_omits_history_callback_without_history(monkeypatch) -> None:
    options = _options(stream_endpoint="", headless=True, history="")
    session = session_runtime.HeadlessChatSession(
        options,
        _startup(),
        _Transport(streaming=False),
        _Initialization(),
    )
    session.runtime = session_runtime._RuntimeComponents(
        workflow=SimpleNamespace(stop=Mock()),
        input_queue=None,
        dialog_queue=None,
        presentation_queue=None,
        ui_worker=None,
        presentation_assets=SimpleNamespace(bgm_paths=[]),
        effect_keyword_map={},
        text_processor=None,
        opencc=None,
    )
    captured = {}
    monkeypatch.setattr(
        "application.runtime.shutdown.shutdown_chat_runtime",
        lambda **kwargs: captured.update(kwargs),
    )

    session._shutdown()

    assert captured["workflow"] is session.runtime.workflow
    assert captured["save_history"] is None
    assert captured["plugin_shutdown"].__self__ is session


def test_headless_run_orders_runtime_start_wait_and_shutdown(monkeypatch) -> None:
    events = []
    options = _options(stream_endpoint="", headless=True)
    initialization = _Initialization()
    session = session_runtime.HeadlessChatSession(
        options,
        _startup(),
        _Transport(streaming=False),
        initialization,
    )
    runtime = session_runtime._RuntimeComponents(
        workflow=SimpleNamespace(),
        input_queue=None,
        dialog_queue=None,
        presentation_queue=None,
        ui_worker=None,
        presentation_assets=SimpleNamespace(bgm_paths=[]),
        effect_keyword_map={},
        text_processor=None,
        opencc=None,
    )

    def build_runtime():
        events.append("build")
        session.runtime = runtime
        return runtime

    monkeypatch.setattr(
        "application.chat.ui_updates.HeadlessUIUpdateManager",
        lambda **_kwargs: "headless-ui",
    )
    monkeypatch.setattr(session, "_build_runtime", build_runtime)
    monkeypatch.setattr(
        session,
        "_create_turn_service",
        lambda: events.append("turn-service"),
    )
    monkeypatch.setattr(
        session,
        "_install_app_runtime",
        lambda: events.append("app-runtime"),
    )
    monkeypatch.setattr(
        session,
        "_start_workflow",
        lambda: events.append("workflow-start"),
    )
    monkeypatch.setattr(
        session,
        "_wait_for_shutdown",
        lambda: events.append("wait"),
    )
    monkeypatch.setattr(session, "_shutdown", lambda: events.append("shutdown"))

    session.run()

    assert events == [
        "build",
        "turn-service",
        "app-runtime",
        "workflow-start",
        "wait",
        "shutdown",
    ]
    assert initialization.completed == 1


def test_streaming_shutdown_supplies_all_lifecycle_callbacks(monkeypatch) -> None:
    transport = _Transport(streaming=True)
    session = session_runtime.StreamingChatSession(
        _options(),
        _startup(),
        transport,
        _Initialization(),
    )
    workflow = SimpleNamespace(stop=Mock())
    session.runtime = session_runtime._RuntimeComponents(
        workflow=workflow,
        input_queue=None,
        dialog_queue=None,
        presentation_queue=None,
        ui_worker=None,
        presentation_assets=SimpleNamespace(bgm_paths=[]),
        effect_keyword_map={},
        text_processor=None,
        opencc=None,
    )
    runtime_asr = SimpleNamespace(close=Mock())
    from core.messaging.chat_turn_service import ChatTurnService
    from core.messaging.continuous_asr_policy import ContinuousASRPolicy
    admitted = []
    turn_service = ChatTurnService(continuous_policy=ContinuousASRPolicy(), sink=admitted.append)
    session.chat_turn_service = turn_service
    active_turn = turn_service.begin_turn()
    turn_service.submit("pending speech", defer_until_idle=True)
    turn_service.mark_generation_complete(active_turn)
    branch_manager = SimpleNamespace(persist=Mock())
    session.streaming_bindings = SimpleNamespace(
        runtime_asr=runtime_asr,
        branch_manager=branch_manager,
    )
    session.ui_updates = SimpleNamespace(
        current_background_path="bg.png",
        current_bgm_path="bgm.mp3",
    )
    captured = {}
    saved_background = []
    monkeypatch.setattr(
        "application.runtime.shutdown.shutdown_chat_runtime",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(
        "application.chat.history_state.save_bg",
        lambda **kwargs: saved_background.append(kwargs),
    )

    session._shutdown()
    captured["pre_shutdown"]()
    captured["save_background"]()
    captured["emit_session_closed"]()

    assert captured["workflow"] is workflow
    runtime_asr.close.assert_called_once_with()
    turn_service.finish_turn(active_turn)
    turn_service.submit("late speech", defer_until_idle=True)
    assert admitted == []
    assert captured["save_history"] == branch_manager.persist
    assert captured["close_stream_sink"] == transport.close
    assert saved_background == [{"bg_path": "bg.png", "bgm_path": "bgm.mp3"}]
    assert transport.events[-1]["type"] == "session.closed"


def test_streaming_shutdown_quiesces_turn_service_and_invalidates_history_before_persistence(
    tmp_path: Path,
) -> None:
    from ai.llm.llm_manager import LLMManager
    from core.chat_history.storage import chat_history_active_path
    from core.messaging.chat_turn_service import ChatTurnService
    from test.mocks import MockLLMAdapter

    history_arg = str(tmp_path / "chat_history.json")
    active_history_file = str(chat_history_active_path(history_arg))
    manager = LLMManager(
        adapter=MockLLMAdapter(),
        user_template="system",
        history_file=active_history_file,
    )
    manager.add_message("user", "hello")
    tmp_path_file = Path(active_history_file + ".tmp")
    assert tmp_path_file.exists()

    turn_service = ChatTurnService()
    active_turn = turn_service.begin_turn()

    worker_scope = manager.history_scope(manager.history_epoch)
    worker_scope.__enter__()

    transport = _Transport(streaming=True)
    session = session_runtime.StreamingChatSession(
        _options(history=history_arg),
        SimpleNamespace(llm_manager=manager, tts_manager=None, plugin_manager=None),
        transport,
        _Initialization(),
    )
    workflow_stopped = False

    def stop_workflow():
        nonlocal workflow_stopped
        workflow_stopped = True

    session.runtime = session_runtime._RuntimeComponents(
        workflow=SimpleNamespace(stop=stop_workflow),
        input_queue=None,
        dialog_queue=None,
        presentation_queue=None,
        ui_worker=None,
        presentation_assets=SimpleNamespace(bgm_paths=[]),
        effect_keyword_map={},
        text_processor=None,
        opencc=None,
    )
    session.chat_turn_service = turn_service
    runtime_asr = SimpleNamespace(close=Mock())
    session.streaming_bindings = SimpleNamespace(
        runtime_asr=runtime_asr,
        branch_manager=SimpleNamespace(
            persist=lambda: session_runtime.save_chat_history_and_delete_tmp(
                history_arg, manager.get_messages()
            )
        ),
    )
    session.ui_updates = SimpleNamespace(
        current_background_path="",
        current_bgm_path="",
    )

    session._shutdown()

    runtime_asr.close.assert_called_once_with()
    assert workflow_stopped is True
    assert not tmp_path_file.exists()

    # 1. Closed turn service rejects turn publication
    with turn_service.turn_publication(active_turn) as allowed:
        assert allowed is False

    # 2. Delayed worker in old scope cannot mutate manager after shutdown
    assert manager.add_message("assistant", "delayed response after shutdown") is False
    assert not any(
        m.get("content") == "delayed response after shutdown"
        for m in manager.get_messages()
    )

    # 3. Delayed worker cannot recreate tmp after shutdown
    assert not tmp_path_file.exists()

    worker_scope.__exit__(None, None, None)


def test_headless_shutdown_quiesces_turn_service_and_invalidates_history_before_persistence(
    tmp_path: Path,
) -> None:
    from ai.llm.llm_manager import LLMManager
    from core.chat_history.storage import chat_history_active_path
    from core.messaging.chat_turn_service import ChatTurnService
    from test.mocks import MockLLMAdapter

    history_arg = str(tmp_path / "headless_history.json")
    active_history_file = str(chat_history_active_path(history_arg))
    manager = LLMManager(
        adapter=MockLLMAdapter(),
        user_template="system",
        history_file=active_history_file,
    )
    manager.add_message("user", "hello headless")
    tmp_path_file = Path(active_history_file + ".tmp")
    assert tmp_path_file.exists()

    turn_service = ChatTurnService()
    active_turn = turn_service.begin_turn()

    worker_scope = manager.history_scope(manager.history_epoch)
    worker_scope.__enter__()

    transport = _Transport(streaming=False)
    session = session_runtime.HeadlessChatSession(
        _options(stream_endpoint="", headless=True, history=history_arg),
        SimpleNamespace(llm_manager=manager, tts_manager=None, plugin_manager=None),
        transport,
        _Initialization(),
    )
    workflow_stopped = False

    def stop_workflow():
        nonlocal workflow_stopped
        workflow_stopped = True

    session.runtime = session_runtime._RuntimeComponents(
        workflow=SimpleNamespace(stop=stop_workflow),
        input_queue=None,
        dialog_queue=None,
        presentation_queue=None,
        ui_worker=None,
        presentation_assets=SimpleNamespace(bgm_paths=[]),
        effect_keyword_map={},
        text_processor=None,
        opencc=None,
    )
    session.chat_turn_service = turn_service

    session._shutdown()

    assert workflow_stopped is True
    assert not tmp_path_file.exists()

    # 1. Closed turn service rejects turn publication
    with turn_service.turn_publication(active_turn) as allowed:
        assert allowed is False

    # 2. Delayed worker in old scope cannot mutate manager after shutdown
    assert manager.add_message("assistant", "delayed headless response") is False
    assert not any(
        m.get("content") == "delayed headless response"
        for m in manager.get_messages()
    )

    # 3. Delayed worker cannot recreate tmp after shutdown
    assert not tmp_path_file.exists()

    worker_scope.__exit__(None, None, None)


def test_shutdown_quiesce_order_and_exception_resilience() -> None:
    events = []

    class FailingTurnService:
        def close(self):
            events.append("close_turn_service")
            raise RuntimeError("close failed")

    class InvalidateManager:
        def invalidate_history(self):
            events.append("invalidate_history")

    session_runtime._quiesce_chat_turn_and_history(
        FailingTurnService(),
        InvalidateManager(),
    )
    # Even if close() raises, invalidate_history() must still be called
    assert events == ["close_turn_service", "invalidate_history"]


def test_streaming_shutdown_order_quiesces_before_capture_and_workflow_and_history() -> None:
    order = []

    class DummyTurnService:
        def close(self):
            order.append("turn_service_close")

    class DummyLlmManager:
        def invalidate_history(self):
            order.append("invalidate_history")

    session = session_runtime.StreamingChatSession(
        _options(),
        SimpleNamespace(llm_manager=DummyLlmManager(), tts_manager=None, plugin_manager=None),
        _Transport(streaming=True),
        _Initialization(),
    )
    session.chat_turn_service = DummyTurnService()
    session.runtime = session_runtime._RuntimeComponents(
        workflow=SimpleNamespace(stop=lambda: order.append("workflow_stop")),
        input_queue=None,
        dialog_queue=None,
        presentation_queue=None,
        ui_worker=None,
        presentation_assets=SimpleNamespace(bgm_paths=[]),
        effect_keyword_map={},
        text_processor=None,
        opencc=None,
    )
    runtime_asr = SimpleNamespace(close=lambda: order.append("asr_close"))
    branch_manager = SimpleNamespace(persist=lambda: order.append("save_history"))
    session.streaming_bindings = SimpleNamespace(
        runtime_asr=runtime_asr,
        branch_manager=branch_manager,
    )
    session.ui_updates = SimpleNamespace(
        current_background_path="",
        current_bgm_path="",
    )

    session._shutdown()

    assert order == [
        "turn_service_close",
        "invalidate_history",
        "asr_close",
        "workflow_stop",
        "save_history",
    ]
