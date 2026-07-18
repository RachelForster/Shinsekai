import copy
import json
import os
from contextlib import contextmanager
from dataclasses import replace
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


def _early_cli_option(name: str) -> str:
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            return args[index + 1]
        prefix = f"{name}="
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return ""


_EARLY_STREAM_ENDPOINT = _early_cli_option("--stream-endpoint")
_EARLY_INIT_STREAM_ENDPOINT = _early_cli_option("--init-stream-endpoint")
_EARLY_STREAM_SINK = None
_EARLY_INIT_STREAM_SINK = None
if _EARLY_STREAM_ENDPOINT:
    try:
        from core.runtime.event_sink import WSClientSink

        _EARLY_STREAM_SINK = WSClientSink(_EARLY_STREAM_ENDPOINT)
        _EARLY_STREAM_SINK.emit({"type": "status.change", "status": "idle"})
    except Exception:
        _EARLY_STREAM_SINK = None
if _EARLY_INIT_STREAM_ENDPOINT:
    try:
        from core.runtime.event_sink import WSClientSink

        _EARLY_INIT_STREAM_SINK = WSClientSink(_EARLY_INIT_STREAM_ENDPOINT)
    except Exception:
        _EARLY_INIT_STREAM_SINK = None

from sdk.chat_init import ChatInitService, InitChatCancelled, InitChatContext

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

import llm.tools.character_tools
import llm.tools.memory_tools
import llm.tools.tool_search
import llm.tools.file_tools
import llm.tools.chat_ui_tools
from llm.template_generator import is_transparent_background
from llm.llm_manager import LLMManager, LLMAdapterFactory
from llm.text_processor import TextProcessor
from core.messaging.chat_turn_wiring import create_chat_turn_service
from core.messaging.queue import ClearableQueue
from core.runtime.app_runtime import AppRuntime, set_app_runtime
from core.runtime.launch_mode import should_init_desktop_mixer
from core.runtime.shutdown import shutdown_chat_runtime
from core.runtime.workflow import build_runtime_workflow, get_chat_workflow_handles
from core.paths import resource_path
from core.sprite.chat_branch_storage import (
    chat_history_active_path,
    load_branch_state,
    reconcile_active_branch_state,
    remove_chat_history_storage,
    save_branch_state,
)
from tts.tts_manager import TTSManager, TTSAdapterFactory
from config.config_manager import ConfigManager
from t2i.t2i_manager import T2IAdapterFactory, T2IManager
import pygame
from opencc import OpenCC
from queue import Queue

from core.sprite.chat_history import (
    chat_history,
    clear_chat_history,
    get_history,
    history_entry_stage_payload,
    history_entry_plain_text,
    load_chat_history,
    is_user_history_entry,
    pop_last_assistant_turn,
    replay_history_entry,
    revert_chat_history,
    save_bg,
    save_chat_history,
)
from core.sprite.chat_ui_service import (
    install_chat_ui_context,
    restore_session_ui,
    wire_chat_ui_bridge,
)
from core.sprite.initial_sprite import display_initial_sprite, find_character_sprite_by_path
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
    "plugins.import": (0.1, 0.13, "Loading plugin runtime."),
    "plugins.load": (0.13, 0.22, "Initializing plugins."),
    "args.parse": (0.22, 0.24, "Reading chat settings."),
    "stream.sink.init": (0.24, 0.26, "Connecting initialization progress."),
    "t2i.init": (0.26, 0.32, "Preparing image generation."),
    "tts.init": (0.32, 0.46, "Starting the voice service."),
    "template.load": (0.46, 0.54, "Loading the chat template and history."),
    "llm.init": (0.54, 0.68, "Preparing the language model."),
    "chat.init_hooks": (0.68, 0.82, "Running chat initialization hooks."),
    "pygame.mixer.init": (0.82, 0.84, "Preparing audio playback."),
    "workflow.build": (0.84, 0.9, "Building the chat workflow."),
    "stream.runtime.setup": (0.9, 0.93, "Connecting the chat interface."),
    "workflow.start": (0.93, 0.96, "Starting the chat workflow."),
    "stream.initial_ui": (0.96, 0.99, "Restoring the chat scene."),
}


def _shutdown_plugins() -> None:
    try:
        from core.plugins.plugin_host import get_plugin_manager

        mgr = get_plugin_manager()
        if mgr is not None:
            mgr.shutdown_all()
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
    from llm.history_manager import HistoryManager

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


def _parse_character_names(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [part.strip() for part in text.split(",")]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _memory_character_names(args, config: ConfigManager) -> list[str]:
    names = _parse_character_names(getattr(args, "characters", ""))
    if names:
        return names
    init_sprite_path = str(getattr(args, "init_sprite_path", "") or "")
    if not init_sprite_path:
        return []
    try:
        matched = find_character_sprite_by_path(config, init_sprite_path)
    except OSError:
        logger.warning(
            "Failed to resolve memory character from initial sprite path",
            extra={"event": "memory.character.resolve_failed", "sprite_path": init_sprite_path},
            exc_info=True,
        )
        return []
    if matched is not None:
        return [matched[0]]
    return []


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
        config = ConfigManager()
    with _startup_phase("i18n.import"):
        from i18n import init_i18n, tr as tr_i18n, tr_in_bundle
        from asr.asr_adapter import system_config_to_asr_lang

    with _startup_phase("i18n.init"):
        init_i18n(config.config.system_config.ui_language)

    with _startup_phase("plugins.import"):
        from core.plugins.plugin_host import ensure_plugins_loaded, wire_user_input_plugins

    with _startup_phase("plugins.load"):
        plugin_manager = ensure_plugins_loaded(config)
    with _startup_phase("args.parse"):
        args = parse_sprite_args(tr_i18n)
    stream_sink = _EARLY_STREAM_SINK if args.stream_endpoint == _EARLY_STREAM_ENDPOINT else None
    if args.stream_endpoint and stream_sink is None:
        with _startup_phase("stream.sink.init"):
            from core.runtime.event_sink import WSClientSink

            stream_sink = WSClientSink(args.stream_endpoint)
            stream_sink.emit({"type": "status.change", "status": "idle"})

    # T2I manager
    t2i_manager = None
    if args.t2i:
        with _startup_phase("t2i.init"):
            raw = (args.t2i or "").strip()
            adapter_pick = (
                (config.config.api_config.t2i_provider or "comfyui").strip()
                if raw.lower() == "comfyui"
                else raw
            )
            try:
                t2i_adapter = T2IAdapterFactory.create_adapter(
                    adapter_name=adapter_pick,
                    **config.merged_t2i_factory_kwargs(
                        adapter_pick,
                        {
                            "work_path": config.config.api_config.t2i_work_path,
                            "api_url": config.config.api_config.t2i_api_url,
                            "workflow_path": config.config.api_config.t2i_default_workflow_path,
                            "prompt_node_id": config.config.api_config.t2i_prompt_node_id,
                            "output_node_id": config.config.api_config.t2i_output_node_id,
                        },
                    ),
                )
                t2i_manager = T2IManager(t2i_adapter)
            except Exception:
                _CHAT_INIT_SERVICE.report(
                    phase="t2i.init",
                    message="Image generation is unavailable; continuing without it.",
                    log="Image generation initialization failed and was skipped.",
                )
                logger.exception("T2I initialization failed", extra={"event": "t2i.init.failed"})

    # TTS
    gsv_url, gsv_api_path, config_tts_provider = config.get_gpt_sovits_config()
    adapter_name = (args.tts or "").strip() or config_tts_provider
    tts_manager = None
    if adapter_name and str(adapter_name).strip().lower() not in ("none",):
        with _startup_phase("tts.init"):
            try:
                adapter = TTSAdapterFactory.create_adapter(
                    adapter_name=adapter_name,
                    wait_until_ready=True,
                    **config.merged_tts_factory_kwargs(
                        adapter_name,
                        {
                            "gpt_sovits_work_path": gsv_api_path,
                            "tts_server_url": gsv_url,
                        },
                    ),
                )
                tts_manager = TTSManager(tts_server_url=gsv_url)
                tts_manager.set_tts_adapter(adapter=adapter)
                _voice_lang = str(config.config.system_config.voice_language or "ja").strip() or "ja"
                tts_manager.set_language(_voice_lang)
            except Exception:
                _CHAT_INIT_SERVICE.report(
                    phase="tts.init",
                    message="Voice service is unavailable; continuing with text chat.",
                    log="Voice service initialization failed and was skipped.",
                )
                logger.exception("TTS initialization failed", extra={"event": "tts.init.failed"})

    print(tr_i18n("main.print_load_template", a=args))

    with _startup_phase("template.load"):
        messages = []
        if args.history:
            print(tr_i18n("main.print_load_history", path=args.history))
            messages = load_chat_history(str(chat_history_active_path(args.history)))

        user_template = ""
        with open(
            f"./data/character_templates/{args.template}.txt", "r", encoding="utf-8"
        ) as f:
            user_template = f.read()

    llm_provider, llm_model, base_url, api_key = config.get_llm_api_config()
    logger.info(
        "LLM configuration selected",
        extra={
            "event": "llm.config.selected",
            "provider": llm_provider,
            "model": llm_model,
            "custom_base_url": bool(base_url),
            "auth_configured": bool(api_key),
        },
    )
    if not llm_provider:
        _CHAT_INIT_SERVICE.failed("No language model provider is configured.")
        print(tr_i18n("main.err_select_llm"))
        return
    with _startup_phase("llm.init"):
        llm_adapter = LLMAdapterFactory.create_adapter(
            **config.merged_llm_factory_kwargs(
                llm_provider,
                {
                    "llm_provider": llm_provider,
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": llm_model,
                },
            )
        )
        llm_manager = LLMManager(
            adapter=llm_adapter,
            user_template=user_template,
            max_tokens=int(config.config.api_config.max_context_tokens),
            compact_threshold=float(config.config.api_config.compact_threshold),
            compact_target_ratio=float(config.config.api_config.compact_target_ratio),
            history_recent_messages=int(config.config.api_config.history_recent_messages),
            max_tool_result_chars=int(config.config.api_config.max_tool_result_chars),
            max_active_tool_groups=int(config.config.api_config.max_active_tool_groups),
            generation_config={
                "temperature": float(config.config.api_config.temperature),
                "repetition_penalty": float(config.config.api_config.repetition_penalty),
                "presence_penalty": float(config.config.api_config.presence_penalty),
                "frequency_penalty": float(config.config.api_config.frequency_penalty),
                "max_tokens": 4096,
            },
            history_file=str(chat_history_active_path(args.history)) if args.history else "",
            hook_dispatcher=(
                plugin_manager.hook_dispatcher if plugin_manager is not None else None
            ),
        )
        if plugin_manager is not None:
            from ai.memory.hooks import install_memory_hooks

            install_memory_hooks(
                plugin_manager.hook_dispatcher,
                llm_adapter=llm_adapter,
                character_names=_memory_character_names(args, config),
            )

    with _startup_phase("chat.init_hooks"):
        if plugin_manager is not None:
            init_context = InitChatContext(
                service=_CHAT_INIT_SERVICE,
                character_names=tuple(_memory_character_names(args, config)),
                tts_provider=str(adapter_name or ""),
                voice_language=str(config.config.system_config.voice_language or "ja"),
                memory_enabled=str(os.environ.get("SHINSEKAI_MEMORY_AUTO_ENABLED") or "1").strip().lower()
                not in {"0", "false", "no", "off"},
                runtime_mode="react" if args.stream_endpoint else "headless" if args.headless else "native",
                headless=bool(args.headless),
                metadata={"workflowPath": str(args.workflow or "")},
            ).scaled(0.68, 0.82)
            plugin_manager.hook_dispatcher.dispatch_init_chat(init_context)

    if messages:
        llm_manager.set_messages(messages)

    image_queue = Queue()
    emotion_queue = Queue()

    if should_init_desktop_mixer(headless=bool(args.headless), stream_endpoint=str(args.stream_endpoint or "")):
        with _startup_phase("pygame.mixer.init"):
            pygame.mixer.init()

    text_processor = TextProcessor()

    for _char in config.config.characters:
        _pm = getattr(_char, "pronunciation_map", None)
        if _pm:
            from llm.text_processor import name_map
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

    # 加载特效方案，构建关键词→音频路径映射
    effect_keyword_map: dict[str, str] = {}
    effect_names_str = (args.effect_names or "").strip()
    if effect_names_str:
        effect_names = [n.strip() for n in effect_names_str.split(",") if n.strip()]
        print(f"[Effect] 加载特效方案: {effect_names}")
        try:
            all_effect_names = [ef.name for ef in config.config.effect_list]
            print(f"[Effect] 可用特效方案: {all_effect_names}")
            for ef in config.config.effect_list:
                if ef.name in effect_names:
                    tags = (ef.audio_tags or "").splitlines()
                    audio_list = ef.audio_list or []
                    print(f"[Effect] 解析 {ef.name}: tags={len(tags)}行, audio={len(audio_list)}个")
                    for i, tag_line in enumerate(tags):
                        tag_line = tag_line.strip()
                        if not tag_line:
                            continue
                        if "：" in tag_line:
                            keyword = tag_line.split("：", 1)[-1].strip()
                        elif ":" in tag_line:
                            keyword = tag_line.split(":", 1)[-1].strip()
                        else:
                            keyword = tag_line
                        if keyword and i < len(audio_list) and audio_list[i]:
                            # 支持逗号分隔多关键词
                            for kw in keyword.split(","):
                                kw = kw.strip()
                                if kw:
                                    effect_keyword_map[kw] = audio_list[i]
                                    print(f"[Effect]   {kw!r} → {audio_list[i]}")
            print(f"[Effect] 关键词映射: {effect_keyword_map}")
        except Exception as e:
            import traceback
            print(f"[Effect] 加载失败: {e}")
            traceback.print_exc()

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
            from core.runtime.ui_update_manager import StreamingUIUpdateManager

            if stream_sink is None:
                from core.runtime.event_sink import WSClientSink

                stream_sink = WSClientSink(args.stream_endpoint)
            ui_updates = StreamingUIUpdateManager(
                stream_sink,
                chat_history=chat_history,
                bg_group=bg_group or [],
            )

            def emit_chat_turn_state(state) -> None:
                stream_sink.emit(
                    {
                        "type": "chat.turn.state",
                        "state": {
                            "enabled": state.enabled,
                            "pendingCount": state.pending_count,
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
        last_user_message = {"text": ""}
        def _default_branch_state() -> dict[str, object]:
            now = int(time.time() * 1000)
            return {
                "active": "main",
                "counter": 1,
                "branches": {
                    "main": {
                        "createdAt": now,
                        "forkedFromEntryId": "",
                        "forkedFromText": "",
                        "history": list(chat_history),
                        "id": "main",
                        "label": "Main",
                        "messages": copy.deepcopy(llm_manager.get_messages()),
                        "parentId": None,
                        "updatedAt": now,
                    }
                },
            }

        def _load_initial_branch_state() -> dict[str, object]:
            restored = load_branch_state(args.history) if args.history else None
            if restored is None:
                return _default_branch_state()
            restored_messages, restored_history = reconcile_active_branch_state(restored, messages, chat_history)
            messages[:] = restored_messages
            chat_history[:] = restored_history
            llm_manager.set_messages(restored_messages)
            return restored

        branch_state: dict[str, object] = _load_initial_branch_state()

        def submit_runtime_text(text: str, *, notify_key: str | None = "main.notify_submitted") -> None:
            value = str(text or "").strip()
            if not value:
                return
            last_user_message["text"] = value
            if emit_user_text is None:
                if notify_key:
                    ui_updates.post_notification(tr_i18n("main.notify_chat"))
                return
            emit_user_text(value)
            if notify_key:
                ui_updates.post_notification(tr_i18n(notify_key))

        def _branch_messages() -> list:
            return copy.deepcopy(llm_manager.get_messages())

        def _branches() -> dict[str, dict[str, object]]:
            return branch_state["branches"]  # type: ignore[return-value]

        def _active_branch_id() -> str:
            return str(branch_state.get("active") or "main")

        def _branch_tree_payload() -> dict[str, object]:
            public_branches = []
            for branch in _branches().values():
                public_branches.append(
                    {
                        "createdAt": branch.get("createdAt"),
                        "forkedFromEntryId": branch.get("forkedFromEntryId") or "",
                        "forkedFromText": branch.get("forkedFromText") or "",
                        "id": str(branch.get("id") or ""),
                        "label": str(branch.get("label") or ""),
                        "parentId": branch.get("parentId"),
                        "updatedAt": branch.get("updatedAt"),
                    }
                )
            return {"activeBranchId": _active_branch_id(), "branches": public_branches}

        def _emit_branch_tree() -> None:
            stream_sink.emit({"type": "conversation.tree", "tree": _branch_tree_payload()})

        def _save_active_branch() -> None:
            branches = _branches()
            active = _active_branch_id()
            branch = branches.get(active)
            if branch is None:
                return
            branch["history"] = list(chat_history)
            branch["messages"] = _branch_messages()
            branch["updatedAt"] = int(time.time() * 1000)

        def _persist_branch_state() -> None:
            if not args.history:
                return
            _save_active_branch()
            _save_chat_history_and_delete_tmp(args.history, llm_manager.get_messages())
            save_branch_state(args.history, branch_state)

        def _reset_branch_state() -> None:
            branch_state.clear()
            branch_state.update(_default_branch_state())

        def _user_history_position(user_index: int) -> int:
            current_user_idx = -1
            for idx, entry in enumerate(chat_history):
                if is_user_history_entry(str(entry)):
                    current_user_idx += 1
                    if current_user_idx == user_index:
                        return idx
            return -1

        def _messages_before_user(user_index: int) -> list:
            new_messages = []
            current_user_idx = -1
            for message in llm_manager.get_messages():
                role = message.get("role")
                if role == "user":
                    current_user_idx += 1
                    if current_user_idx >= user_index:
                        break
                new_messages.append(copy.deepcopy(message))
            return new_messages

        def _plain_user_text(history_entry: object) -> str:
            text = history_entry_plain_text(history_entry)
            for separator in ("：", ":"):
                if separator in text:
                    speaker, body = text.split(separator, 1)
                    if speaker.strip() in {"你", "User", "user"}:
                        return body.strip()
            return text.strip()

        def _fork_history_branch(user_index: int) -> None:
            if user_index < 0:
                raise ValueError("分支索引无效。")
            _save_active_branch()
            user_pos = _user_history_position(user_index)
            if user_pos < 0:
                raise ValueError("找不到可分叉的历史记录。")
            source_entry = chat_history[user_pos]
            user_text = _plain_user_text(source_entry)
            if not user_text:
                raise ValueError("分支输入内容为空。")
            prefix_history = list(chat_history[:user_pos])
            prefix_messages = _messages_before_user(user_index)
            branch_state["counter"] = int(branch_state.get("counter") or 1) + 1
            branch_id = f"branch-{branch_state['counter']}"
            now = int(time.time() * 1000)
            _branches()[branch_id] = {
                "createdAt": now,
                "forkedFromEntryId": f"history-{user_pos}",
                "forkedFromText": user_text,
                "history": list(prefix_history),
                "id": branch_id,
                "label": f"Branch {branch_state['counter']}",
                "messages": copy.deepcopy(prefix_messages),
                "parentId": _active_branch_id(),
                "updatedAt": now,
            }
            branch_state["active"] = branch_id
            chat_history[:] = prefix_history
            llm_manager.set_messages(copy.deepcopy(prefix_messages))
            stream_sink.emit({"type": "options.clear"})
            if hasattr(ui_updates, "sync_history_entries"):
                ui_updates.sync_history_entries()
            _emit_branch_tree()
            _persist_branch_state()
            submit_runtime_text(user_text, notify_key=None)

        def _switch_history_branch(branch_id: str) -> None:
            target_id = str(branch_id or "").strip()
            branches = _branches()
            if not target_id or target_id not in branches:
                raise ValueError("对话分支不存在。")
            _save_active_branch()
            branch = branches[target_id]
            branch_state["active"] = target_id
            chat_history[:] = list(branch.get("history") or [])
            llm_manager.set_messages(copy.deepcopy(branch.get("messages") or []))
            stream_sink.emit({"type": "options.clear"})
            if hasattr(ui_updates, "sync_history_entries"):
                ui_updates.sync_history_entries()
            if chat_history:
                replay_history_entry(_StreamWindowProxy(ui_updates), str(chat_history[-1]))
            _emit_branch_tree()
            _persist_branch_state()
            ui_updates.post_notification("已切换对话分支。")

        def _rename_history_branch(branch_id: str, label: str) -> None:
            target_id = str(branch_id or "").strip()
            next_label = str(label or "").strip()
            if not target_id or target_id not in _branches():
                raise ValueError("对话分支不存在。")
            if not next_label:
                raise ValueError("分支名称不能为空。")
            _branches()[target_id]["label"] = next_label[:64]
            _branches()[target_id]["updatedAt"] = int(time.time() * 1000)
            _emit_branch_tree()
            _persist_branch_state()
            ui_updates.post_notification("已重命名对话分支。")

        def handle_stream_command(command: dict[str, object]) -> None:
            command_type = str(command.get("type") or "").strip()
            cmd_id = str(command.get("cmdId") or "").strip()
            payload = command.get("payload")
            ack_sent = False

            def emit_ack(*, ok: bool, error: str = "") -> None:
                nonlocal ack_sent
                if ack_sent or not cmd_id:
                    return
                stream_sink.emit(
                    {
                        "type": "cmd.ack",
                        "cmdId": cmd_id,
                        "commandType": command_type,
                        "ok": bool(ok),
                        **({"error": error} if error else {}),
                    }
                )
                ack_sent = True

            try:
                if command_type == "close-session":
                    emit_ack(ok=True)
                    shutdown_requested.set()
                    return
                if command_type == "send-message":
                    submit_runtime_text(str(payload or ""), notify_key=None)
                    emit_ack(ok=True)
                    return
                if command_type == "submit-option":
                    submit_runtime_text(str(payload or ""))
                    emit_ack(ok=True)
                    return
                if command_type == "update-turn-options":
                    if not isinstance(payload, dict):
                        raise ValueError("Chat turn options must be an object.")
                    interrupt_enabled = payload.get("interruptEnabled")
                    batch_enabled = payload.get("batchEnabled")
                    batch_idle_seconds = payload.get("batchIdleSeconds")
                    if not isinstance(interrupt_enabled, bool) or not isinstance(batch_enabled, bool):
                        raise ValueError("Chat turn switches must be boolean values.")
                    if isinstance(batch_idle_seconds, bool) or not isinstance(batch_idle_seconds, (int, float)):
                        raise ValueError("Batch input timeout must be numeric.")
                    timeout = float(batch_idle_seconds)
                    if not 0.3 <= timeout <= 120.0:
                        raise ValueError("Batch input timeout must be between 0.3 and 120 seconds.")
                    chat_turn_service.update_options(
                        replace(
                            chat_turn_service.options,
                            interrupt_enabled=interrupt_enabled,
                            batch_enabled=batch_enabled,
                            batch_idle_seconds=timeout,
                        )
                    )
                    api_config = config.config.api_config.model_copy(deep=True)
                    api_config.interrupt_enabled = interrupt_enabled
                    api_config.is_batch_input_enabled = batch_enabled
                    api_config.batch_input_timeout = timeout
                    config.config.api_config = api_config
                    emit_ack(ok=True)
                    return
                if command_type == "chat-input-state":
                    if not isinstance(payload, dict):
                        raise ValueError("Chat input state must be an object.")
                    chat_turn_service.input_changed(
                        has_text=bool(payload.get("hasText")),
                        composing=bool(payload.get("composing")),
                    )
                    emit_ack(ok=True)
                    return
                if command_type == "flush-input-batch":
                    chat_turn_service.flush()
                    emit_ack(ok=True)
                    return
                if command_type == "cancel-input-batch":
                    chat_turn_service.cancel_pending_batch()
                    emit_ack(ok=True)
                    return
                if command_type in {"skip-speech", "dialog-advance"}:
                    if _um is not None and hasattr(_um, "skip_speech"):
                        _um.skip_speech()
                    emit_ack(ok=True)
                    return
                if command_type == "pause-asr":
                    ui_updates.post_pause_asr()
                    emit_ack(ok=True)
                    return
                if command_type == "resume-asr":
                    stream_sink.emit({"type": "asr.state", "running": True})
                    emit_ack(ok=True)
                    return
                if command_type == "reroll":
                    messages_ref = llm_manager.get_messages()
                    if hasattr(llm_manager, "_strip_orphaned_tool_calls"):
                        llm_manager._strip_orphaned_tool_calls()
                    reroll_text = pop_last_assistant_turn(chat_history, messages_ref)
                    if not reroll_text:
                        reroll_text = last_user_message["text"]
                    else:
                        plain_text = history_entry_plain_text(reroll_text)
                        if plain_text.startswith("你："):
                            reroll_text = plain_text[2:].strip()
                        elif plain_text.startswith("你:"):
                            reroll_text = plain_text[2:].strip()
                        else:
                            reroll_text = plain_text
                    stream_sink.emit({"type": "options.clear"})
                    if hasattr(ui_updates, "sync_history_entries"):
                        ui_updates.sync_history_entries()
                    if reroll_text and emit_user_text is not None:
                        last_user_message["text"] = reroll_text
                        emit_user_text(reroll_text)
                        ui_updates.post_notification(tr_i18n("main.notify_reroll"))
                    emit_ack(ok=True)
                    return
                if command_type == "clear-history":
                    if audio_path_queue is None:
                        raise RuntimeError("聊天历史清理队列未就绪。")
                    history_target = str(chat_history_active_path(args.history)) if args.history else str(
                        Path("data/chat_history") / "_temp.json"
                    )
                    clear_chat_history(history_target, audio_path_queue, llm_manager)
                    if args.history:
                        remove_chat_history_storage(args.history)
                    _reset_branch_state()
                    _persist_branch_state()
                    stream_sink.emit({"type": "options.clear"})
                    if hasattr(ui_updates, "sync_history_entries"):
                        ui_updates.sync_history_entries()
                    _emit_branch_tree()
                    emit_ack(ok=True)
                    return
                if command_type == "change-voice-language":
                    voice_language = str(payload or "").strip().lower()
                    if not voice_language:
                        raise ValueError("语音语言不能为空。")
                    if tts_manager is not None:
                        tts_manager.set_language(voice_language)
                    voice_labels = {
                        "en": "template.voice_lang_en",
                        "zh": "template.voice_lang_zh",
                        "ja": "template.voice_lang_ja",
                        "yue": "template.voice_lang_yue",
                    }
                    sc = config.config.system_config.model_copy(deep=True)
                    sc.voice_language = voice_language
                    config.config.system_config = sc
                    config.save_system_config()
                    ui_updates.post_notification(
                        tr_i18n(
                            "desktop.menu.notify_voice_language",
                            lang=tr_i18n(voice_labels.get(voice_language, "template.voice_lang_en")),
                        )
                    )
                    emit_ack(ok=True)
                    return
                if command_type == "revert-history":
                    index = int(payload)
                    revert_chat_history(
                        index,
                        llm_manager=llm_manager,
                        hist=chat_history,
                        window=_StreamWindowProxy(ui_updates),
                    )
                    stream_sink.emit({"type": "options.clear"})
                    if hasattr(ui_updates, "sync_history_entries"):
                        ui_updates.sync_history_entries()
                    emit_ack(ok=True)
                    return
                if command_type == "fork-history":
                    raw_index = payload.get("userIndex") if isinstance(payload, dict) else payload
                    _fork_history_branch(int(raw_index))
                    emit_ack(ok=True)
                    return
                if command_type == "switch-branch":
                    _switch_history_branch(str(payload or ""))
                    emit_ack(ok=True)
                    return
                if command_type == "rename-branch":
                    raw_payload = payload if isinstance(payload, dict) else {}
                    _rename_history_branch(str(raw_payload.get("branchId") or ""), str(raw_payload.get("label") or ""))
                    emit_ack(ok=True)
                    return
                raise ValueError(f"未知实时聊天命令：{command_type}")
            except Exception as exc:
                ui_updates.post_notification(str(exc))
                emit_ack(ok=False, error=str(exc))

        shutdown_requested = threading.Event()
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
                restored_sprite = restore_session_ui(
                    messages,
                    audio_path_queue=audio_path_queue,
                    window=_StreamWindowProxy(ui_updates),
                    config=config,
                    tr_i18n=tr_i18n,
                )

            if not messages:
                ui_updates.post_dialog_html(_welcome_html, is_system=True, color="#84C2D5")
                if len(get_history()) <= 1:
                    ui_updates.post_options([_option_start])
            _emit_branch_tree()
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
                plugin_shutdown=_shutdown_plugins,
                tts_shutdown=(lambda: tts_manager.shutdown()) if tts_manager else None,
                save_history=_persist_branch_state,
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
        from core.runtime.ui_update_manager import HeadlessUIUpdateManager

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

    from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from ui.chat_ui.chat_ui import ChatUIWindow
    from ui.chat_ui.chat_turn_controller import ChatTurnController
    from ui.chat_ui.qss_fusion import ensure_fusion_style

    app = QApplication([])
    ensure_fusion_style(app)
    from ui.event_filters import install_no_wheel_filter
    install_no_wheel_filter(app)
    ui_updates = UIUpdateManager(chat_history=chat_history, bg_group=bg_group or [])
    window = ChatUIWindow(
        image_queue,
        emotion_queue,
        llm_manager,
        sprite_mode=True,
        background_mode=(bg_group is not None),
    )
    connect_to_desktop_window(ui_updates, window)
    mirror_stream_sink = None
    if args.mirror_stream_endpoint:
        from core.runtime.event_sink import WSClientSink
        from core.runtime.ui_update_manager import connect_to_stream_sink

        mirror_stream_sink = WSClientSink(args.mirror_stream_endpoint)
        connect_to_stream_sink(ui_updates, mirror_stream_sink)

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

    init_sprite_path = args.init_sprite_path
    print(init_sprite_path)
    if not init_sprite_path and not is_transparent_background(args.bg):
        init_sprite_path = str(resource_path("assets/system/picture/shinsekai.png"))

    if system_config_to_asr_lang(config.config.system_config) == "zh":
        _welcome_html = tr_in_bundle("main.welcome_html", "zh_CN")
        _option_start = tr_in_bundle("main.option_start", "zh_CN")
    else:
        _welcome_html = tr_i18n("main.welcome_html")
        _option_start = tr_i18n("main.option_start")

    try:
        if not messages:
            window.setDisplayWords(_welcome_html)
            if len(get_history()) <= 1:
                window.setOptions([_option_start])
    except Exception:
        if not messages:
            window.setDisplayWords(_welcome_html)
    window.setNotification(tr_i18n("main.notify_chat"))

    if user_input_queue is not None:
        emit_user_text = wire_user_input_plugins(user_input_queue, sink=chat_turn_service.submit)
    else:
        emit_user_text = None

    window._chat_turn_controller = ChatTurnController(window, chat_turn_service, ui_updates)

    sc = config.config.system_config.model_copy(deep=True)
    if bg_group:
        sc.bgm_path = bgm_list[0] if bgm_list else ""
        sc.background_path = bg_group[0].get("path", "") if bg_group else ""
    else:
        sc.bgm_path = ""
        sc.background_path = ""
    config.config.system_config = sc
    config.save_system_config()

    chat_ui_ctx = install_chat_ui_context(window, emit_user_text=emit_user_text)

    restored_sprite = False
    if audio_path_queue is not None:
        restored_sprite = restore_session_ui(
            messages,
            audio_path_queue=audio_path_queue,
            window=window,
            config=config,
            tr_i18n=tr_i18n,
        )
    if not restored_sprite:
        display_initial_sprite(
            init_sprite_path,
            config=config,
            ui_updates=ui_updates,
        )

    wire_chat_ui_bridge(
        chat_ui_ctx,
        window=window,
        app=app,
        emit_user_text=emit_user_text,
        chat_history=chat_history,
        history_file=args.history,
        llm_manager=llm_manager,
        audio_path_queue=audio_path_queue,
        tts_manager=tts_manager,
        ui_worker=_um,
        tr_i18n=tr_i18n,
    )

    if args.room_id:
        print(tr_i18n("main.print_bili_start", id=args.room_id))
        if user_input_queue is not None:
            try:
                start_bilibili_service(args.room_id, user_input_queue=user_input_queue)
            except ImportError as e:
                pass

    try:
        appIcon = QIcon(str(resource_path("assets/system/picture/Icon.png")))
        app.setWindowIcon(appIcon)
    except Exception as e:
        print(tr_i18n("main.print_icon_fail", e=str(e)))

    # 关闭顺序：会话关闭事件（如有）→ Worker 线程 → 插件/TTS → 保存数据
    app.aboutToQuit.connect(
        lambda: shutdown_chat_runtime(
            workflow=workflow,
            plugin_shutdown=_shutdown_plugins,
            tts_shutdown=(lambda: tts_manager.shutdown()) if tts_manager else None,
            save_history=lambda: _save_chat_history_and_delete_tmp(args.history, llm_manager.get_messages())
            if args.history else None,
            save_background=lambda: save_bg(
                bg_path=window.current_background_path,
                bgm_path=ui_updates.current_bgm_path,
            ),
            emit_session_closed=(
                lambda: mirror_stream_sink.emit({"type": "session.closed", "reason": "聊天会话已结束。"})
            )
            if mirror_stream_sink is not None
            else None,
            close_stream_sink=mirror_stream_sink.close if mirror_stream_sink is not None else None,
            on_error=_log_shutdown_error,
        )
    )

    window.show()
    _finish_chat_initialization()

    app.exec()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit, InitChatCancelled):
        _CHAT_INIT_SERVICE.cancelled()
        raise
    except BaseException as exc:
        _fail_chat_initialization(exc)
        handle_main_exception(exc, app_name="Shinsekai Chat", logger=logger)
