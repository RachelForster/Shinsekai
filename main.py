import os
from contextlib import contextmanager
from pathlib import Path
import signal
import sys
import threading
import time

_PROCESS_STARTED_AT = time.perf_counter()

# Frozen standalone keeps the old release-root data behavior. Desktop bridge
# launches can provide SHINSEKAI_PROJECT_ROOT (or legacy EASYAI_PROJECT_ROOT)
# to keep chat data independent from the application install directory.
if getattr(sys, "frozen", False):
    try:
        _rel = Path(sys.executable).resolve().parent.parent
        _data_root = Path(
            os.environ.get("SHINSEKAI_PROJECT_ROOT")
            or os.environ.get("EASYAI_PROJECT_ROOT")
            or _rel
        ).expanduser().resolve(strict=False)
        _data_root.mkdir(parents=True, exist_ok=True)
        os.environ["SHINSEKAI_PROJECT_ROOT"] = str(_data_root)
        os.environ["EASYAI_PROJECT_ROOT"] = str(_data_root)
        os.environ.setdefault("SHINSEKAI_APP_ROOT", str(_rel))
        os.chdir(_data_root)
    except OSError:
        pass

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from core.sprite.sprite_cli import load_sprite_launch_config

_LAUNCH_CONFIG = load_sprite_launch_config()


def _early_cli_option(name: str) -> str:
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            return args[index + 1]
        prefix = f"{name}="
        if arg.startswith(prefix):
            return arg[len(prefix):]
    config_key = name.lstrip("-").replace("-", "_")
    return str(_LAUNCH_CONFIG.get(config_key) or "")


_EARLY_STREAM_ENDPOINT = _early_cli_option("--stream-endpoint")
_EARLY_INIT_STREAM_ENDPOINT = _early_cli_option("--init-stream-endpoint")
_EARLY_STREAM_SINK = None
_EARLY_INIT_STREAM_SINK = None
if _EARLY_STREAM_ENDPOINT:
    try:
        from frontend_bridge_core.transport.ws_client import WSClientSink

        _EARLY_STREAM_SINK = WSClientSink(_EARLY_STREAM_ENDPOINT)
        _EARLY_STREAM_SINK.emit({"type": "status.change", "status": "idle"})
    except Exception:
        _EARLY_STREAM_SINK = None
if _EARLY_INIT_STREAM_ENDPOINT:
    try:
        from frontend_bridge_core.transport.ws_client import WSClientSink

        _EARLY_INIT_STREAM_SINK = WSClientSink(_EARLY_INIT_STREAM_ENDPOINT)
    except Exception:
        _EARLY_INIT_STREAM_SINK = None

from sdk.chat_init import ChatInitService, InitChatCancelled

_CHAT_INIT_SINK = _EARLY_INIT_STREAM_SINK or _EARLY_STREAM_SINK
_CHAT_INIT_SERVICE = ChatInitService(_CHAT_INIT_SINK.emit if _CHAT_INIT_SINK is not None else None)
_CHAT_INIT_SERVICE.start()

if getattr(sys, "frozen", False):
    from core.bootstrap.frozen_log import init_frozen_stdio

    init_frozen_stdio("main")

from sdk.logging import configure_logging, get_logger
from sdk.exception.handler import handle_main_exception, install_main_exception_hook

configure_logging("chat", project_root=os.environ.get("EASYAI_PROJECT_ROOT") or project_root)
logger = get_logger(__name__)
install_main_exception_hook(app_name="Shinsekai Chat", logger=logger)

_STARTUP_IMPORTS_STARTED_AT = time.perf_counter()
from config.mirror_env import apply_mirror_environment_from_system_config
from config.network_proxy import apply_network_proxy_environment_from_system_config

apply_network_proxy_environment_from_system_config()
apply_mirror_environment_from_system_config()

import ai.tools.character_tools
import ai.tools.memory_tools
import ai.tools.tool_search
import ai.tools.file_tools
import ai.tools.chat_ui_tools
import ai.tools.story_tools
from ai.llm.template_generator import is_transparent_background
from ai.llm.text_processor import TextProcessor
from application.chat.turn_wiring import create_chat_turn_service
from core.messaging.queue import ClearableQueue
from application.runtime.context import (
    AppRuntime,
    resolve_pending_tool_confirmation,
    set_app_runtime,
)
from application.runtime.shutdown import shutdown_chat_runtime
from application.runtime.workflow import build_runtime_workflow, get_chat_workflow_handles
from core.media.chat_attachments import resolve_chat_attachments
from core.paths import resource_path
from core.sprite.chat_branch_storage import (
    chat_history_active_path,
)
from opencc import OpenCC
from queue import Queue

from application.chat.effects import build_selected_effect_context
from application.chat.commands import (
    ChatCommandBindings,
    ChatCommandDispatcher,
    ChatCommandUiBindings,
)
from application.chat.manage_branches import (
    ConversationBranchBindings,
    ConversationBranchManager,
)
from application.chat.history_state import (
    chat_history,
    get_history,
    history_entry_stage_payload,
    replay_history_entry,
    save_bg,
    save_chat_history,
)
from frontend_bridge_core.transport.chat_commands import (
    parse_chat_command,
    send_chat_command_ack,
)
from application.chat.session_restore import restore_session_presentation
from application.chat.initial_sprite import (
    display_initial_sprite,
)
from application.chat.startup import (
    chat_history_is_present,
    create_chat_startup_context,
    load_chat_config,
    MissingLlmProviderError,
)
from core.sprite.sprite_cli import parse_sprite_args
logger.info(
    "Chat startup imports completed",
    extra={
        "event": "chat.startup.imports.completed",
        "duration_ms": round((time.perf_counter() - _STARTUP_IMPORTS_STARTED_AT) * 1000, 2),
        "process_elapsed_ms": round((time.perf_counter() - _PROCESS_STARTED_AT) * 1000, 2),
    },
)
try:
    from live.danmuku_handler import start_bilibili_service
except ImportError as e:
    pass

voice_lang = "ja"
cc = OpenCC("t2s")

_CHAT_INIT_PHASES: dict[str, tuple[float, float, str]] = {
    "config.load": (0.02, 0.06, "Loading configuration."),
    "i18n.import": (0.06, 0.08, "Loading language support."),
    "i18n.init": (0.08, 0.1, "Preparing translations."),
    "args.parse": (0.1, 0.12, "Reading chat settings."),
    "stream.sink.init": (0.12, 0.14, "Connecting initialization progress."),
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


def _shutdown_plugins() -> None:
    try:
        from plugin_system.host import (
            bind_frontend_ui_runtime,
            get_plugin_manager,
        )

        mgr = get_plugin_manager()
        if mgr is not None:
            mgr.shutdown_all()
        bind_frontend_ui_runtime(None)
    except Exception:
        pass


def _log_shutdown_error(step: str, exc: Exception) -> None:
    logger.error(
        "chat runtime shutdown step failed",
        extra={"event": "chat.shutdown.failed", "step": step},
        exc_info=(type(exc), exc, exc.__traceback__),
    )


def _save_chat_history_and_delete_tmp(history_arg: str, messages: list) -> bool:
    if not history_arg:
        return True
    from ai.llm.history_manager import HistoryManager

    history_file = str(chat_history_active_path(history_arg))
    success = save_chat_history(history_file, messages)
    if not success:
        return False
    try:
        HistoryManager.delete_tmp(history_file)
    except Exception as exc:
        _log_shutdown_error("delete_tmp", exc)
    return True


@contextmanager
def _startup_phase(step: str):
    started = time.perf_counter()
    phase_start, phase_end, phase_message = _CHAT_INIT_PHASES.get(
        step,
        (_CHAT_INIT_SERVICE.snapshot().get("progress") or 0.0, None, f"Preparing {step}."),
    )
    _CHAT_INIT_SERVICE.phase_started(step, phase_message, progress=float(phase_start))
    logger.info(
        "Chat startup step started",
        extra={"event": "chat.startup.step.started", "step": step},
    )
    try:
        yield
    except InitChatCancelled:
        _CHAT_INIT_SERVICE.cancelled()
        raise
    except Exception as exc:
        _CHAT_INIT_SERVICE.failed(exc, message=f"Failed while {phase_message.rstrip('.').lower()}.")
        logger.exception(
            "Chat startup step failed",
            extra={
                "event": "chat.startup.step.failed",
                "step": step,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__,
            },
        )
        raise
    else:
        _CHAT_INIT_SERVICE.phase_completed(
            step,
            phase_message,
            progress=float(phase_end) if phase_end is not None else None,
        )
        logger.info(
            "Chat startup step completed",
            extra={
                "event": "chat.startup.step.completed",
                "step": step,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )


def _finish_chat_initialization() -> None:
    _CHAT_INIT_SERVICE.completed()
    if _EARLY_INIT_STREAM_SINK is not None:
        try:
            _EARLY_INIT_STREAM_SINK.close()
        except Exception:
            logger.debug("failed to close initialization progress sink", exc_info=True)


def _fail_chat_initialization(exc: BaseException) -> None:
    _CHAT_INIT_SERVICE.failed(exc)
    if _EARLY_INIT_STREAM_SINK is not None:
        try:
            _EARLY_INIT_STREAM_SINK.close()
        except Exception:
            logger.debug("failed to close initialization progress sink", exc_info=True)


def _install_interrupt_handlers():
    registered = []

    def _raise_interrupt(_signum, _frame):
        raise KeyboardInterrupt()

    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous = signal.getsignal(sig)
            signal.signal(sig, _raise_interrupt)
        except (OSError, RuntimeError, ValueError):
            continue
        registered.append((sig, previous))

    def _restore():
        for sig, previous in registered:
            try:
                signal.signal(sig, previous)
            except (OSError, RuntimeError, ValueError):
                continue

    return _restore


class _StreamWindowProxy:
    def __init__(self, ui_updates):
        self._ui_updates = ui_updates

    def setBackgroundImage(self, path: str) -> None:
        self._ui_updates.post_background(path)

    def setDisplayWords(self, text: str) -> None:
        if hasattr(self._ui_updates, "post_dialog_html"):
            payload = history_entry_stage_payload(text)
            self._ui_updates.post_dialog_html(
                payload.get("fullHtml", text),
                append_history=False,
                speaker=str(payload.get("speaker") or ""),
                color=str(payload.get("color") or "#84C2D5"),
                is_system=bool(payload.get("isSystem")),
            )

    def setOptions(self, options) -> None:
        self._ui_updates.post_options(list(options or []))


def main():
    main_started = time.perf_counter()
    logger.info("Chat application starting", extra={"event": "app.started"})
    with _startup_phase("config.load"):
        config = load_chat_config()
    with _startup_phase("i18n.import"):
        from i18n import init_i18n, tr as tr_i18n, tr_in_bundle
        from ai.asr.asr_adapter import (
            create_default_asr_adapter,
            system_config_to_asr_lang,
        )

    with _startup_phase("i18n.init"):
        init_i18n(config.config.system_config.ui_language)

    with _startup_phase("args.parse"):
        args = parse_sprite_args(tr_i18n, defaults=_LAUNCH_CONFIG)
    if not args.stream_endpoint and not args.headless:
        raise SystemExit(
            "The Qt chat window has been retired; launch chat through React/Tauri "
            "or pass --headless."
        )
    stream_sink = _EARLY_STREAM_SINK if args.stream_endpoint == _EARLY_STREAM_ENDPOINT else None
    if args.stream_endpoint and stream_sink is None:
        with _startup_phase("stream.sink.init"):
            from frontend_bridge_core.transport.ws_client import WSClientSink

            stream_sink = WSClientSink(args.stream_endpoint)
            stream_sink.emit({"type": "status.change", "status": "idle"})

    def _bind_plugin_frontend(plugin_manager) -> None:
        from plugin_system.host import bind_frontend_ui_runtime

        bind_frontend_ui_runtime(
            stream_sink.emit
            if plugin_manager is not None and stream_sink is not None
            else None
        )

    try:
        startup = create_chat_startup_context(
            args,
            config=config,
            init_service=_CHAT_INIT_SERVICE,
            translate=tr_i18n,
            phase=_startup_phase,
            on_plugins_loaded=_bind_plugin_frontend,
        )
    except MissingLlmProviderError as exc:
        _CHAT_INIT_SERVICE.failed(str(exc))
        print(tr_i18n("main.err_select_llm"))
        return

    config = startup.config
    llm_manager = startup.llm_manager
    tts_manager = startup.tts_manager
    t2i_manager = startup.t2i_manager
    plugin_manager = startup.plugin_manager
    messages = startup.messages
    active_history_present = chat_history_is_present(args.history)

    from plugin_system.host import wire_user_input_plugins

    image_queue = Queue()
    emotion_queue = Queue()

    text_processor = TextProcessor()

    for _char in config.config.characters:
        _pm = getattr(_char, "pronunciation_map", None)
        if _pm:
            from ai.llm.text_processor import name_map
            name_map.update(_pm)

    bg_group = None
    try:
        bg_group = (
            None
            if is_transparent_background(args.bg)
            else config.get_background_by_name(args.bg).sprites
        )
    except Exception:
        pass

    bgm_list = []
    try:
        bgm_list = (
            []
            if is_transparent_background(args.bg)
            else config.get_background_by_name(args.bg).bgm_list
        )
    except Exception:
        pass

    # Resolve the selected effects once through the application-level projection.
    effect_names_str = (args.effect_names or "").strip()
    effect_context = build_selected_effect_context(config, effect_names_str)
    effect_keyword_map = effect_context.keyword_map

    if args.headless and not args.stream_endpoint and not (args.workflow or "").strip():
        headless_workflow = str(resource_path("assets/system/workflow/headless.yaml"))
    else:
        headless_workflow = None

    with _startup_phase("workflow.build"):
        workflow = build_runtime_workflow(
            workflow_path=args.workflow or headless_workflow,
            queue_factory=ClearableQueue,
        )
        chat_handles = get_chat_workflow_handles(workflow)
    user_input_queue = chat_handles.input_queue
    audio_path_queue = chat_handles.audio_queue
    tts_queue = chat_handles.tts_queue
    _um = chat_handles.ui_worker

    if args.stream_endpoint:
        with _startup_phase("stream.runtime.setup"):
            from application.chat.ui_updates import StreamingUIUpdateManager

            if stream_sink is None:
                from frontend_bridge_core.transport.ws_client import WSClientSink

                stream_sink = WSClientSink(args.stream_endpoint)
            ui_updates = StreamingUIUpdateManager(
                stream_sink,
                chat_history=chat_history,
                bg_group=bg_group or [],
            )

            def emit_chat_turn_state(state) -> None:
                options = chat_turn_service.options
                stream_sink.emit(
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

            chat_turn_service = create_chat_turn_service(
                config=config,
                user_input_queue=user_input_queue,
                tts_queue=tts_queue,
                audio_queue=audio_path_queue,
                llm_manager=llm_manager,
                ui_worker=_um,
                ui_updates=ui_updates,
                on_state_change=emit_chat_turn_state,
            )
            emit_chat_turn_state(chat_turn_service.batch_state())
            set_app_runtime(
                AppRuntime(
                    config=config,
                    ui_update_manager=ui_updates,
                    llm_manager=llm_manager,
                    tts_manager=tts_manager,
                    t2i_manager=t2i_manager,
                    bgm_list=bgm_list,
                    effect_keyword_map=effect_keyword_map,
                    user_input_queue=user_input_queue,
                    tts_queue=tts_queue,
                    audio_path_queue=audio_path_queue,
                    text_processor=text_processor,
                    opencc=cc,
                    chat_turn_service=chat_turn_service,
                )
            )
            if hasattr(ui_updates, "sync_history_entries"):
                ui_updates.sync_history_entries()

            emit_user_text = (
                wire_user_input_plugins(user_input_queue, sink=chat_turn_service.submit)
                if user_input_queue is not None
                else None
            )
        last_user_message: dict[str, object] = {"attachments": [], "text": ""}

        def submit_runtime_text(
            text: str,
            *,
            attachments: list[dict[str, object]] | None = None,
            ignore_unavailable_attachments: bool = False,
            notify_key: str | None = "main.notify_submitted",
        ) -> bool:
            value = str(text or "").strip()
            try:
                resolved_attachments = resolve_chat_attachments(attachments)
            except (OSError, ValueError):
                if not ignore_unavailable_attachments:
                    raise
                resolved_attachments = []
                for attachment in attachments or []:
                    try:
                        resolved_attachments.extend(resolve_chat_attachments([attachment]))
                    except (OSError, ValueError):
                        continue
            if not value and not resolved_attachments:
                return False
            last_user_message["text"] = value
            last_user_message["attachments"] = [attachment.to_payload() for attachment in resolved_attachments]
            if emit_user_text is None:
                if notify_key:
                    ui_updates.post_notification(tr_i18n("main.notify_chat"))
                return False
            accepted = emit_user_text(value, attachments=last_user_message["attachments"])
            if accepted is False:
                return False
            if notify_key:
                ui_updates.post_notification(tr_i18n(notify_key))
            return True

        branch_manager = ConversationBranchManager(
            history_path=args.history,
            chat_history=chat_history,
            bindings=ConversationBranchBindings(
                get_messages=llm_manager.get_messages,
                set_messages=llm_manager.set_messages,
                cancel_pending_batch=chat_turn_service.cancel_pending_batch,
                persist_messages=lambda current_messages: (
                    _save_chat_history_and_delete_tmp(args.history, current_messages)
                ),
                publish_tree=lambda tree: stream_sink.emit(
                    {"type": "conversation.tree", "tree": tree}
                ),
                clear_options=lambda: stream_sink.emit({"type": "options.clear"}),
                sync_history=lambda: (
                    ui_updates.sync_history_entries()
                    if hasattr(ui_updates, "sync_history_entries")
                    else None
                ),
                replay_history=lambda entry: replay_history_entry(
                    _StreamWindowProxy(ui_updates), str(entry)
                ),
                submit_text=submit_runtime_text,
            ),
        )
        branch_manager.load(
            messages,
            active_history_present=active_history_present,
        )

        from ai.asr.streaming_controller import StreamingASRController

        def _submit_asr_text(text: str) -> bool:
            accepted = submit_runtime_text(text, notify_key=None)
            if not accepted:
                return False
            if chat_turn_service.options.batch_enabled:
                # Voice mode is turn-based: a completed utterance must not remain
                # buffered behind the stacked-message idle timer.
                chat_turn_service.flush()
            stream_sink.emit({"type": "status.change", "status": "generating"})
            return True

        def _set_asr_loading(loading: bool) -> None:
            if loading:
                ui_updates.post_busy_bar(tr_i18n("desktop.mic_loading_model"), 0.0)
            else:
                ui_updates.hide_busy_bar()

        def _report_asr_error(operation: str, exc: BaseException) -> None:
            logger.error(
                "Streaming ASR %s failed",
                operation,
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={"event": "asr.streaming.failed", "operation": operation},
            )
            ui_updates.post_notification(str(exc))

        runtime_asr = StreamingASRController(
            adapter_factory=create_default_asr_adapter,
            emit_event=stream_sink.emit,
            submit_final=_submit_asr_text,
            on_loading_changed=_set_asr_loading,
            on_error=_report_asr_error,
            resume_delay_seconds=0.5,
        )
        original_post_llm_reply_finished = ui_updates.post_llm_reply_finished

        def _post_pause_asr_for_reply() -> None:
            # The streaming controller owns the distinction between a user-disabled
            # microphone and the temporary pause used while the character replies.
            runtime_asr.pause_for_turn()

        def _post_llm_reply_finished_and_resume_asr() -> None:
            original_post_llm_reply_finished()
            runtime_asr.reply_finished()

        ui_updates.post_pause_asr = _post_pause_asr_for_reply
        ui_updates.post_llm_reply_finished = _post_llm_reply_finished_and_resume_asr

        shutdown_requested = threading.Event()

        def _clear_stream_options() -> None:
            stream_sink.emit({"type": "options.clear"})

        def _sync_stream_history() -> None:
            if hasattr(ui_updates, "sync_history_entries"):
                ui_updates.sync_history_entries()

        def _clear_tool_confirmation(confirmation_id: str) -> None:
            if hasattr(ui_updates, "clear_tool_confirmation"):
                ui_updates.clear_tool_confirmation(confirmation_id)

        def _handle_playback_signal(
            playback_id: str,
            playback_state: str,
            error: str,
            renderer_id: str,
        ) -> None:
            _um.handle_playback_signal(
                playback_id,
                playback_state,
                error,
                renderer_id=renderer_id,
            )

        command_dispatcher = ChatCommandDispatcher(
            bindings=ChatCommandBindings(
                submit_text=submit_runtime_text,
                can_submit_text=lambda: emit_user_text is not None,
                shutdown_session=shutdown_requested.set,
                resolve_tool_confirmation=resolve_pending_tool_confirmation,
                ui=ChatCommandUiBindings(
                    clear_options=_clear_stream_options,
                    sync_history=_sync_stream_history,
                    notify=ui_updates.post_notification,
                    clear_tool_confirmation=_clear_tool_confirmation,
                    handle_playback_signal=(
                        _handle_playback_signal
                        if _um is not None and hasattr(_um, "handle_playback_signal")
                        else None
                    ),
                    skip_speech=(
                        _um.skip_speech
                        if _um is not None and hasattr(_um, "skip_speech")
                        else None
                    ),
                ),
                translate=tr_i18n,
            ),
            config=config,
            llm_manager=llm_manager,
            runtime_asr=runtime_asr,
            chat_turn_service=chat_turn_service,
            branch_manager=branch_manager,
            chat_history=chat_history,
            last_user_message=last_user_message,
            audio_path_queue=audio_path_queue,
            history_argument=args.history,
            history_presenter=_StreamWindowProxy(ui_updates),
            tts_manager=tts_manager,
        )

        def handle_stream_command(command: dict[str, object]) -> None:
            request = parse_chat_command(command)
            result = command_dispatcher.execute(request)
            send_chat_command_ack(stream_sink.emit, request, result)

        stream_sink.set_command_handler(handle_stream_command)
        with _startup_phase("workflow.start"):
            workflow.start()

        with _startup_phase("stream.initial_ui"):
            init_sprite_path = args.init_sprite_path
            if not init_sprite_path and not is_transparent_background(args.bg):
                init_sprite_path = str(resource_path("assets/system/picture/shinsekai.png"))

            if system_config_to_asr_lang(config.config.system_config) == "zh":
                _welcome_html = tr_in_bundle("main.welcome_html", "zh_CN")
                _option_start = tr_in_bundle("main.option_start", "zh_CN")
            else:
                _welcome_html = tr_i18n("main.welcome_html")
                _option_start = tr_i18n("main.option_start")

            sc = config.config.system_config.model_copy(deep=True)
            if bg_group:
                sc.bgm_path = bgm_list[0] if bgm_list else ""
                sc.background_path = bg_group[0].get("path", "") if bg_group else ""
            else:
                sc.bgm_path = ""
                sc.background_path = ""
            config.config.system_config = sc
            config.save_system_config()

            if bg_group:
                try:
                    ui_updates.post_background(bg_group[0].get("path", ""))
                except Exception:
                    pass
            ui_updates.switch_bgm(bgm_list[0] if bgm_list else "")

            restored_sprite = False
            if audio_path_queue is not None:
                restored_sprite = restore_session_presentation(
                    messages,
                    audio_path_queue=audio_path_queue,
                    presenter=_StreamWindowProxy(ui_updates),
                    config=config,
                    tr_i18n=tr_i18n,
                )

            if not messages:
                ui_updates.post_dialog_html(_welcome_html, is_system=True, color="#84C2D5")
                if len(get_history()) <= 1:
                    ui_updates.post_options([_option_start])
            branch_manager.publish_tree()
            ui_updates.post_notification(tr_i18n("main.notify_chat"))

            if not restored_sprite:
                display_initial_sprite(
                    init_sprite_path,
                    config=config,
                    ui_updates=ui_updates,
                )

        _finish_chat_initialization()

        if args.room_id:
            print(tr_i18n("main.print_bili_start", id=args.room_id))
            if user_input_queue is not None:
                try:
                    start_bilibili_service(args.room_id, user_input_queue=user_input_queue)
                except ImportError:
                    pass

        logger.info(
            "Chat application ready",
            extra={
                "event": "chat.startup.ready",
                "mode": "stream",
                "duration_ms": round((time.perf_counter() - main_started) * 1000, 2),
            },
        )

        try:
            restore_interrupt_handlers = _install_interrupt_handlers()
            while not shutdown_requested.wait(1):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            restore_interrupt_handlers()
            shutdown_chat_runtime(
                workflow=workflow,
                pre_shutdown=runtime_asr.close,
                plugin_shutdown=_shutdown_plugins,
                tts_shutdown=(lambda: tts_manager.shutdown()) if tts_manager else None,
                save_history=branch_manager.persist,
                save_background=lambda: save_bg(
                    bg_path=ui_updates.current_background_path,
                    bgm_path=ui_updates.current_bgm_path,
                ),
                emit_session_closed=lambda: stream_sink.emit(
                    {"type": "session.closed", "reason": "聊天会话已结束。"}
                ),
                close_stream_sink=stream_sink.close,
                on_error=_log_shutdown_error,
            )
        return

    if args.headless:
        from application.chat.ui_updates import HeadlessUIUpdateManager

        ui_updates = HeadlessUIUpdateManager(chat_history=chat_history)
        chat_turn_service = create_chat_turn_service(
            config=config,
            user_input_queue=user_input_queue,
            tts_queue=tts_queue,
            audio_queue=audio_path_queue,
            llm_manager=llm_manager,
            ui_worker=_um,
            ui_updates=ui_updates,
        )
        set_app_runtime(
            AppRuntime(
                config=config,
                ui_update_manager=ui_updates,
                llm_manager=llm_manager,
                tts_manager=tts_manager,
                t2i_manager=t2i_manager,
                bgm_list=bgm_list,
                effect_keyword_map=effect_keyword_map,
                user_input_queue=user_input_queue,
                tts_queue=tts_queue,
                audio_path_queue=audio_path_queue,
                text_processor=text_processor,
                opencc=cc,
                chat_turn_service=chat_turn_service,
            )
        )
        workflow.start()
        _finish_chat_initialization()
        print(f"Workflow started: {args.workflow or 'default'}")
        try:
            restore_interrupt_handlers = _install_interrupt_handlers()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            restore_interrupt_handlers()
            shutdown_chat_runtime(
                workflow=workflow,
                plugin_shutdown=_shutdown_plugins,
                tts_shutdown=(lambda: tts_manager.shutdown()) if tts_manager else None,
                save_history=lambda: _save_chat_history_and_delete_tmp(args.history, llm_manager.get_messages())
                if args.history else None,
                on_error=_log_shutdown_error,
            )
        return

    raise SystemExit("The Qt chat window has been retired; launch chat through React/Tauri or pass --headless.")

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit, InitChatCancelled):
        _CHAT_INIT_SERVICE.cancelled()
        raise
    except BaseException as exc:
        _fail_chat_initialization(exc)
        handle_main_exception(exc, app_name="Shinsekai Chat", logger=logger)
