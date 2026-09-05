from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat import session_runtime


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
    config = SimpleNamespace(config=SimpleNamespace(characters=[]))
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
        lambda *_args: SimpleNamespace(bgm_paths=[], background_sprites=[]),
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
    session = session_runtime.StreamingChatSession(
        options,
        _startup(config),
        _Transport(streaming=True),
        _Initialization(),
    )

    session._build_runtime()

    factory.assert_called_once_with("semantic")
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
    captured["save_background"]()
    captured["emit_session_closed"]()

    assert captured["workflow"] is workflow
    assert captured["pre_shutdown"] == runtime_asr.close
    assert captured["save_history"] == branch_manager.persist
    assert captured["close_stream_sink"] == transport.close
    assert saved_background == [{"bg_path": "bg.png", "bgm_path": "bgm.mp3"}]
    assert transport.events[-1]["type"] == "session.closed"
