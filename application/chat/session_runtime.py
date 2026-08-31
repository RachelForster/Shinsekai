"""Own chat session runtime composition and lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import signal
import sys
import threading
import time
from typing import Any, Protocol

from application.chat.startup import (
    ChatStartupContext,
    MissingLlmProviderError,
    create_chat_startup_context,
    load_chat_config,
)
from sdk.chat_init import ChatInitService, InitChatCancelled


logger = logging.getLogger(__name__)


_CHAT_INIT_PHASES: dict[str, tuple[float, float, str]] = {
    "config.load": (0.02, 0.06, "Loading configuration."),
    "i18n.import": (0.06, 0.08, "Loading language support."),
    "i18n.init": (0.08, 0.1, "Preparing translations."),
    "args.parse": (0.1, 0.14, "Reading chat settings."),
    "plugins.import": (0.14, 0.17, "Loading plugin runtime."),
    "plugins.load": (0.17, 0.26, "Initializing plugins."),
    "t2i.init": (0.26, 0.32, "Preparing image generation."),
    "tts.init": (0.32, 0.46, "Starting the voice service."),
    "template.load": (0.46, 0.54, "Loading the chat template and history."),
    "llm.init": (0.54, 0.68, "Preparing the language model."),
    "chat.init_hooks": (0.68, 0.82, "Running chat initialization hooks."),
    "workflow.build": (0.84, 0.9, "Building the chat workflow."),
    "stream.runtime.setup": (0.9, 0.93, "Connecting the chat interface."),
    "workflow.start": (0.93, 0.96, "Starting the chat workflow."),
    "stream.initial_ui": (0.96, 0.99, "Restoring the chat scene."),
}


class ChatSessionTransport(Protocol):
    stream_sink: Any | None

    @property
    def streaming(self) -> bool: ...

    def emit(self, payload: dict[str, Any]) -> None: ...

    def emit_initialization(self, payload: dict[str, Any]) -> None: ...

    def bind_command_dispatcher(self, dispatcher: Any) -> None: ...

    def close_initialization(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ChatLaunchOptions:
    """Parsed process options and adapters required to create a chat session."""

    args: Any
    config: Any
    translate: Callable[..., str]
    translate_bundle: Callable[..., str]
    create_asr_adapter: Callable[..., Any]
    asr_language: Callable[[Any], str]
    started_at: float


@dataclass(frozen=True, slots=True)
class ChatBootstrapEndpoints:
    """Producer endpoints available before full launch option parsing."""

    stream_endpoint: str = ""
    init_stream_endpoint: str = ""


@dataclass(slots=True)
class _RuntimeComponents:
    workflow: Any
    input_queue: Any | None
    tts_queue: Any | None
    audio_queue: Any | None
    ui_worker: Any | None
    presentation_assets: Any
    effect_keyword_map: dict[str, str]
    text_processor: Any
    opencc: Any


class _ChatInitialization:
    def __init__(self, transport: ChatSessionTransport) -> None:
        self.transport = transport
        self.service = ChatInitService(transport.emit_initialization)
        self.service.start()

    @contextmanager
    def phase(self, step: str):
        started = time.perf_counter()
        phase_start, phase_end, phase_message = _CHAT_INIT_PHASES.get(
            step,
            (
                self.service.snapshot().get("progress") or 0.0,
                None,
                f"Preparing {step}.",
            ),
        )
        self.service.phase_started(step, phase_message, progress=float(phase_start))
        logger.info(
            "Chat startup step started",
            extra={"event": "chat.startup.step.started", "step": step},
        )
        try:
            yield
        except SystemExit as exc:
            if exc.code is None or exc.code == 0:
                self.service.cancelled()
            else:
                self.service.failed(
                    exc,
                    message=f"Failed while {phase_message.rstrip('.').lower()}.",
                )
            raise
        except InitChatCancelled:
            self.service.cancelled()
            raise
        except Exception as exc:
            self.service.failed(
                exc,
                message=f"Failed while {phase_message.rstrip('.').lower()}.",
            )
            logger.exception(
                "Chat startup step failed",
                extra={
                    "event": "chat.startup.step.failed",
                    "step": step,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000,
                        2,
                    ),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        else:
            self.service.phase_completed(
                step,
                phase_message,
                progress=float(phase_end) if phase_end is not None else None,
            )

    def complete(self) -> None:
        self.service.completed()
        self.transport.close_initialization()

    def fail(self, exc: BaseException | str) -> None:
        self.service.failed(exc)
        self.transport.close_initialization()

    def cancel(self) -> None:
        self.service.cancelled()
        self.transport.close_initialization()


_active_initialization: _ChatInitialization | None = None


def peek_launch_endpoints() -> ChatBootstrapEndpoints:
    """Read early producer endpoints without consuming bridge launch config."""

    from application.chat.launch_args import peek_chat_launch_endpoints

    launch_config = peek_chat_launch_endpoints()
    return ChatBootstrapEndpoints(
        stream_endpoint=_early_launch_option(
            "--stream-endpoint",
            "stream_endpoint",
            launch_config,
        ),
        init_stream_endpoint=_early_launch_option(
            "--init-stream-endpoint",
            "init_stream_endpoint",
            launch_config,
        ),
    )


def parse_launch_options(transport: ChatSessionTransport) -> ChatLaunchOptions:
    """Load process configuration, translations, and command-line launch options."""

    started_at = time.perf_counter()
    initialization = _initialization_for(transport)
    from config.mirror_env import apply_mirror_environment_from_system_config
    from config.network_proxy import apply_network_proxy_environment_from_system_config

    apply_network_proxy_environment_from_system_config()
    apply_mirror_environment_from_system_config()
    _import_builtin_tools()

    with initialization.phase("config.load"):
        config = load_chat_config()
    with initialization.phase("i18n.import"):
        from i18n import init_i18n, tr, tr_in_bundle
        from ai.asr.asr_adapter import (
            create_default_asr_adapter,
            system_config_to_asr_lang,
        )
        from application.chat.launch_args import load_chat_launch_config, parse_chat_args

    with initialization.phase("i18n.init"):
        init_i18n(config.config.system_config.ui_language)
    with initialization.phase("args.parse"):
        args = parse_chat_args(tr, defaults=load_chat_launch_config())
    if not args.stream_endpoint and not args.headless:
        raise SystemExit(
            "The Qt chat window has been retired; launch chat through React/Tauri "
            "or pass --headless."
        )
    return ChatLaunchOptions(
        args=args,
        config=config,
        translate=tr,
        translate_bundle=tr_in_bundle,
        create_asr_adapter=create_default_asr_adapter,
        asr_language=system_config_to_asr_lang,
        started_at=started_at,
    )


def create_chat_session(
    options: ChatLaunchOptions,
    transport: ChatSessionTransport,
) -> StreamingChatSession | HeadlessChatSession:
    """Create the selected session after assembling provider dependencies."""

    initialization = _initialization_for(transport)

    def bind_plugin_frontend(plugin_manager: Any | None) -> None:
        from plugin_system.host import bind_frontend_ui_runtime

        bind_frontend_ui_runtime(
            transport.emit
            if plugin_manager is not None and transport.streaming
            else None
        )

    try:
        startup = create_chat_startup_context(
            options.args,
            config=options.config,
            init_service=initialization.service,
            translate=options.translate,
            phase=initialization.phase,
            on_plugins_loaded=bind_plugin_frontend,
        )
    except MissingLlmProviderError as exc:
        initialization.fail(exc)
        print(options.translate("main.err_select_llm"))
        raise

    if options.args.stream_endpoint:
        return StreamingChatSession(options, startup, transport, initialization)
    if options.args.headless:
        return HeadlessChatSession(options, startup, transport, initialization)
    raise SystemExit(
        "The Qt chat window has been retired; launch chat through React/Tauri "
        "or pass --headless."
    )


def cancel_chat_initialization() -> None:
    if _active_initialization is not None:
        _active_initialization.cancel()


def fail_chat_initialization(exc: BaseException) -> None:
    if _active_initialization is not None:
        _active_initialization.fail(exc)


def _initialization_for(transport: ChatSessionTransport) -> _ChatInitialization:
    global _active_initialization
    current = _active_initialization
    if current is not None and current.transport is transport:
        status = str(current.service.snapshot().get("status") or "")
        if status not in {"succeeded", "failed", "cancelled"}:
            return current
    current = _ChatInitialization(transport)
    _active_initialization = current
    return current


def _early_launch_option(
    cli_name: str,
    config_name: str,
    launch_config: dict[str, Any],
) -> str:
    args = sys.argv[1:]
    cli_value: str | None = None
    for index, argument in enumerate(args):
        if (
            argument == cli_name
            and index + 1 < len(args)
            and not args[index + 1].startswith("-")
        ):
            cli_value = str(args[index + 1] or "").strip()
        prefix = f"{cli_name}="
        if argument.startswith(prefix):
            cli_value = str(argument[len(prefix) :] or "").strip()
    if cli_value is not None:
        return cli_value
    return str(launch_config.get(config_name) or "").strip()


class _BaseChatSession:
    mode = "unknown"

    def __init__(
        self,
        options: ChatLaunchOptions,
        startup: ChatStartupContext,
        transport: ChatSessionTransport,
        initialization: _ChatInitialization,
    ) -> None:
        self.options = options
        self.args = options.args
        self.startup = startup
        self.transport = transport
        self.initialization = initialization
        self.runtime: _RuntimeComponents | None = None
        self.ui_updates: Any | None = None
        self.chat_turn_service: Any | None = None
        self._shutdown_requested = threading.Event()

    @property
    def config(self) -> Any:
        return self.startup.config

    def _build_runtime(self) -> _RuntimeComponents:
        from ai.llm.text_processor import TextProcessor, name_map
        from application.chat.effects import build_selected_effect_context
        from application.chat.presentation import load_presentation_assets
        from application.runtime.workflow import (
            build_runtime_workflow,
            get_chat_workflow_handles,
        )
        from core.messaging.queue import ClearableQueue
        from core.paths import resource_path
        from opencc import OpenCC

        for character in self.config.config.characters:
            pronunciation_map = getattr(character, "pronunciation_map", None)
            if pronunciation_map:
                name_map.update(pronunciation_map)

        assets = load_presentation_assets(self.config, self.args.bg)
        effect_context = build_selected_effect_context(
            self.config,
            str(self.args.effect_names or "").strip(),
        )
        workflow_path = str(self.args.workflow or "").strip()
        if self.mode == "headless" and not workflow_path:
            workflow_path = str(resource_path("assets/system/workflow/headless.yaml"))
        with self.initialization.phase("workflow.build"):
            workflow = build_runtime_workflow(
                workflow_path=workflow_path,
                queue_factory=ClearableQueue,
            )
            handles = get_chat_workflow_handles(workflow)
        self.runtime = _RuntimeComponents(
            workflow=workflow,
            input_queue=handles.input_queue,
            tts_queue=handles.tts_queue,
            audio_queue=handles.audio_queue,
            ui_worker=handles.ui_worker,
            presentation_assets=assets,
            effect_keyword_map=effect_context.keyword_map,
            text_processor=TextProcessor(),
            opencc=OpenCC("t2s"),
        )
        return self.runtime

    def _create_turn_service(
        self,
        *,
        on_state_change: Callable[[Any], None] | None = None,
    ) -> Any:
        from application.chat.turn_wiring import create_chat_turn_service

        runtime = self._require_runtime()
        self.chat_turn_service = create_chat_turn_service(
            config=self.config,
            user_input_queue=runtime.input_queue,
            tts_queue=runtime.tts_queue,
            audio_queue=runtime.audio_queue,
            llm_manager=self.startup.llm_manager,
            ui_worker=runtime.ui_worker,
            ui_updates=self.ui_updates,
            on_state_change=on_state_change,
        )
        return self.chat_turn_service

    def _install_app_runtime(self) -> None:
        from application.runtime.context import AppRuntime, set_app_runtime

        runtime = self._require_runtime()
        set_app_runtime(
            AppRuntime(
                config=self.config,
                ui_update_manager=self.ui_updates,
                llm_manager=self.startup.llm_manager,
                tts_manager=self.startup.tts_manager,
                t2i_manager=self.startup.t2i_manager,
                bgm_list=runtime.presentation_assets.bgm_paths,
                effect_keyword_map=runtime.effect_keyword_map,
                user_input_queue=runtime.input_queue,
                tts_queue=runtime.tts_queue,
                audio_path_queue=runtime.audio_queue,
                text_processor=runtime.text_processor,
                opencc=runtime.opencc,
                chat_turn_service=self.chat_turn_service,
            )
        )

    def _start_workflow(self) -> None:
        with self.initialization.phase("workflow.start"):
            self._require_runtime().workflow.start()

    def _wait_for_shutdown(self) -> None:
        restore_interrupt_handlers = _install_interrupt_handlers()
        try:
            while not self._shutdown_requested.wait(1):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            restore_interrupt_handlers()

    def _shutdown_plugins(self) -> None:
        from plugin_system.host import bind_frontend_ui_runtime

        try:
            if self.startup.plugin_manager is not None:
                self.startup.plugin_manager.shutdown_all()
        finally:
            bind_frontend_ui_runtime(None)

    def _tts_shutdown(self) -> Callable[[], None] | None:
        manager = self.startup.tts_manager
        return manager.shutdown if manager is not None else None

    def _require_runtime(self) -> _RuntimeComponents:
        if self.runtime is None:
            raise RuntimeError("chat session runtime has not been built")
        return self.runtime


class StreamingChatSession(_BaseChatSession):
    """Run a realtime chat session backed by a streaming transport."""

    mode = "stream"

    def run(self) -> None:
        from application.chat.history_state import chat_history
        from application.chat.ui_updates import StreamingUIUpdateManager

        runtime = self._build_runtime()
        with self.initialization.phase("stream.runtime.setup"):
            self.ui_updates = StreamingUIUpdateManager(
                self.transport.stream_sink,
                chat_history=chat_history,
                bg_group=runtime.presentation_assets.background_sprites,
            )
            self._configure_stream_runtime()
        self._start_workflow()
        self._present_initial_ui()
        self.initialization.complete()
        self._start_live_comments()
        self._log_ready()
        try:
            self._wait_for_shutdown()
        finally:
            self._shutdown()

    def _configure_stream_runtime(self) -> None:
        from application.chat.wire_streaming_session import wire_streaming_session

        runtime = self._require_runtime()

        def emit_chat_turn_state(state: Any) -> None:
            options = self.chat_turn_service.options
            self.transport.emit(
                {
                    "options": {
                        "batchEnabled": options.batch_enabled,
                        "batchIdleSeconds": options.batch_idle_seconds,
                        "interruptEnabled": options.interrupt_enabled,
                    },
                    "type": "chat.turn.state",
                    "state": {
                        "enabled": state.enabled,
                        "pendingCount": state.pending_count,
                        "pendingMessages": list(state.pending_messages),
                        "remainingSeconds": state.remaining_seconds,
                        "scheduled": state.scheduled,
                        "typing": state.typing,
                    },
                }
            )

        turn_service = self._create_turn_service(on_state_change=emit_chat_turn_state)
        emit_chat_turn_state(turn_service.batch_state())
        self._install_app_runtime()
        if hasattr(self.ui_updates, "sync_history_entries"):
            self.ui_updates.sync_history_entries()
        self.streaming_bindings = wire_streaming_session(
            args=self.args,
            config=self.config,
            startup=self.startup,
            transport=self.transport,
            runtime=runtime,
            ui_updates=self.ui_updates,
            chat_turn_service=turn_service,
            shutdown_session=self._shutdown_requested.set,
            translate=self.options.translate,
            create_asr_adapter=self.options.create_asr_adapter,
            save_history=save_chat_history_and_delete_tmp,
        )

    def _present_initial_ui(self) -> None:
        from application.chat.presentation import prepare_initial_presentation

        if self.options.asr_language(self.config.config.system_config) == "zh":
            welcome_html = self.options.translate_bundle(
                "main.welcome_html",
                "zh_CN",
            )
            initial_option = self.options.translate_bundle(
                "main.option_start",
                "zh_CN",
            )
        else:
            welcome_html = self.options.translate("main.welcome_html")
            initial_option = self.options.translate("main.option_start")
        with self.initialization.phase("stream.initial_ui"):
            prepare_initial_presentation(
                messages=self.startup.messages,
                config=self.config,
                ui_updates=self.ui_updates,
                audio_path_queue=self._require_runtime().audio_queue,
                assets=self._require_runtime().presentation_assets,
                initial_sprite_path=self.args.init_sprite_path,
                welcome_html=welcome_html,
                initial_option=initial_option,
                ready_notification=self.options.translate("main.notify_chat"),
                publish_branch_tree=self.streaming_bindings.branch_manager.publish_tree,
                translate=self.options.translate,
            )

    def _start_live_comments(self) -> None:
        if not self.args.room_id or self._require_runtime().input_queue is None:
            return
        print(self.options.translate("main.print_bili_start", id=self.args.room_id))
        try:
            from live.danmuku_handler import start_bilibili_service

            start_bilibili_service(
                self.args.room_id,
                user_input_queue=self._require_runtime().input_queue,
            )
        except ImportError:
            pass

    def _log_ready(self) -> None:
        logger.info(
            "Chat application ready",
            extra={
                "event": "chat.startup.ready",
                "mode": self.mode,
                "duration_ms": round(
                    (time.perf_counter() - self.options.started_at) * 1000,
                    2,
                ),
            },
        )

    def _shutdown(self) -> None:
        from application.chat.history_state import save_bg
        from application.runtime.shutdown import shutdown_chat_runtime

        runtime = self._require_runtime()
        shutdown_chat_runtime(
            workflow=runtime.workflow,
            pre_shutdown=self.streaming_bindings.runtime_asr.close,
            plugin_shutdown=self._shutdown_plugins,
            tts_shutdown=self._tts_shutdown(),
            save_history=self.streaming_bindings.branch_manager.persist,
            save_background=lambda: save_bg(
                bg_path=self.ui_updates.current_background_path,
                bgm_path=self.ui_updates.current_bgm_path,
            ),
            emit_session_closed=lambda: self.transport.emit(
                {"type": "session.closed", "reason": "聊天会话已结束。"}
            ),
            close_stream_sink=self.transport.close,
            on_error=_log_shutdown_error,
        )


class HeadlessChatSession(_BaseChatSession):
    """Run a chat workflow without an interactive presentation transport."""

    mode = "headless"

    def run(self) -> None:
        from application.chat.history_state import chat_history
        from application.chat.ui_updates import HeadlessUIUpdateManager

        self._build_runtime()
        self.ui_updates = HeadlessUIUpdateManager(chat_history=chat_history)
        self._create_turn_service()
        self._install_app_runtime()
        self._start_workflow()
        self.initialization.complete()
        print(f"Workflow started: {self.args.workflow or 'default'}")
        try:
            self._wait_for_shutdown()
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        from application.runtime.shutdown import shutdown_chat_runtime

        runtime = self._require_runtime()
        save_history = None
        if self.args.history:

            def persist_history() -> bool:
                return save_chat_history_and_delete_tmp(
                    self.args.history,
                    self.startup.llm_manager.get_messages(),
                )

            save_history = persist_history
        shutdown_chat_runtime(
            workflow=runtime.workflow,
            plugin_shutdown=self._shutdown_plugins,
            tts_shutdown=self._tts_shutdown(),
            save_history=save_history,
            on_error=_log_shutdown_error,
        )


def save_chat_history_and_delete_tmp(
    history_argument: str, messages: list[Any]
) -> bool:
    """Persist active messages and remove the history manager temporary file."""

    if not history_argument:
        return True
    from ai.llm.history_manager import HistoryManager
    from application.chat.history_state import save_chat_history
    from core.chat_history.storage import chat_history_active_path

    history_file = str(chat_history_active_path(history_argument))
    success = save_chat_history(history_file, messages)
    if not success:
        return False
    try:
        HistoryManager.delete_tmp(history_file)
    except Exception as exc:
        _log_shutdown_error("delete_tmp", exc)
    return True


def _install_interrupt_handlers() -> Callable[[], None]:
    registered: list[tuple[Any, Any]] = []

    def raise_interrupt(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt()

    for name in ("SIGINT", "SIGTERM"):
        selected_signal = getattr(signal, name, None)
        if selected_signal is None:
            continue
        try:
            previous = signal.getsignal(selected_signal)
            signal.signal(selected_signal, raise_interrupt)
        except (OSError, RuntimeError, ValueError):
            continue
        registered.append((selected_signal, previous))

    def restore() -> None:
        for selected_signal, previous in registered:
            try:
                signal.signal(selected_signal, previous)
            except (OSError, RuntimeError, ValueError):
                continue

    return restore


def _log_shutdown_error(step: str, exc: Exception) -> None:
    logger.error(
        "chat runtime shutdown step failed",
        extra={"event": "chat.shutdown.failed", "step": step},
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def _import_builtin_tools() -> None:
    """Import built-in tool modules so their registrations are available."""

    import ai.tools.character_tools  # noqa: F401
    import ai.tools.chat_ui_tools  # noqa: F401
    import ai.tools.file_tools  # noqa: F401
    import ai.tools.memory_tools  # noqa: F401
    import ai.tools.story_tools  # noqa: F401
    import ai.tools.tool_search  # noqa: F401
