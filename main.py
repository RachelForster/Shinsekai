import os
from pathlib import Path
import sys

# Frozen standalone keeps the old release-root data behavior. Desktop bridge
# launches can provide EASYAI_PROJECT_ROOT to keep chat data under app data.
if getattr(sys, "frozen", False):
    try:
        _rel = Path(sys.executable).resolve().parent.parent
        _data_root = Path(os.environ.get("EASYAI_PROJECT_ROOT") or _rel).expanduser().resolve(strict=False)
        _data_root.mkdir(parents=True, exist_ok=True)
        os.environ["EASYAI_PROJECT_ROOT"] = str(_data_root)
        os.environ.setdefault("SHINSEKAI_APP_ROOT", str(_rel))
        os.chdir(_data_root)
    except OSError:
        pass

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

if getattr(sys, "frozen", False):
    from core.bootstrap.frozen_log import init_frozen_stdio

    init_frozen_stdio("main")

from sdk.logging import configure_logging, get_logger
from sdk.exception.handler import handle_main_exception, install_main_exception_hook

configure_logging("chat", project_root=os.environ.get("EASYAI_PROJECT_ROOT") or project_root)
logger = get_logger(__name__)
install_main_exception_hook(app_name="Shinsekai Chat", logger=logger)

from config.mirror_env import apply_mirror_environment_from_system_config

apply_mirror_environment_from_system_config()

import llm.tools.character_tools
import llm.tools.memory_tools
import llm.tools.tool_search
import llm.tools.file_tools
from llm.template_generator import is_transparent_background
from llm.llm_manager import LLMManager, LLMAdapterFactory
from llm.text_processor import TextProcessor
from core.runtime.app_runtime import AppRuntime, set_app_runtime
from core.runtime.workflow import build_runtime_workflow, get_chat_workflow_handles
from core.paths import resource_path
from tts.tts_manager import TTSManager, TTSAdapterFactory
from config.config_manager import ConfigManager
from t2i.t2i_manager import T2IAdapterFactory, T2IManager
import pygame
from opencc import OpenCC
from queue import Queue

from core.sprite.chat_history import (
    chat_history,
    get_history,
    load_chat_history,
    save_bg,
    save_chat_history,
)
from core.sprite.chat_ui_service import (
    install_chat_ui_context,
    restore_session_ui,
    wire_chat_ui_bridge,
)
from core.sprite.initial_sprite import display_initial_sprite
from core.sprite.sprite_cli import parse_sprite_args
try:
    from live.danmuku_handler import start_bilibili_service
except ImportError as e:
    # 早于 init_i18n，不调用 tr
    # print("Bilibili import failed:", e)
    pass

voice_lang = "ja"
cc = OpenCC("t2s")  # 繁体到简体转换器


def _shutdown_plugins() -> None:
    try:
        from core.plugins.plugin_host import get_plugin_manager

        mgr = get_plugin_manager()
        if mgr is not None:
            mgr.shutdown_all()
    except Exception:
        pass


def main():
    logger.info("Chat application starting", extra={"event": "app.started"})
    config = ConfigManager()
    from i18n import init_i18n, tr as tr_i18n, tr_in_bundle
    from asr.asr_adapter import system_config_to_asr_lang

    init_i18n(config.config.system_config.ui_language)

    from core.plugins.plugin_host import ensure_plugins_loaded, wire_user_input_plugins

    ensure_plugins_loaded(config)

    args = parse_sprite_args(tr_i18n)

    # T2I manager
    t2i_manager = None
    if args.t2i:
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
            logger.exception("T2I initialization failed", extra={"event": "t2i.init.failed"})

    # TTS：仅当 API 中语音引擎不是「不使用」时加载；命令行 --tts 可覆盖引擎名（与 api.yaml 一致）
    gsv_url, gsv_api_path, config_tts_provider = config.get_gpt_sovits_config()
    adapter_name = (args.tts or "").strip() or config_tts_provider
    tts_manager = None
    if adapter_name and str(adapter_name).strip().lower() not in ("none",):
        try:
            adapter = TTSAdapterFactory.create_adapter(
                adapter_name=adapter_name,
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
            logger.exception("TTS initialization failed", extra={"event": "tts.init.failed"})

    print(tr_i18n("main.print_load_template", a=args))

    messages = []
    if args.history:
        print(tr_i18n("main.print_load_history", path=args.history))
        messages = load_chat_history(args.history)

    user_template = ""
    with open(
        f"./data/character_templates/{args.template}.txt", "r", encoding="utf-8"
    ) as f:
        user_template = f.read()

    # Init LLMManager before UI, so that handlers can access it via get_app_runtime().llm_manager
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
        print(tr_i18n("main.err_select_llm"))
        return
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
        history_file=args.history,  # ← 新增，用于增量保存
    )

    if messages:
        llm_manager.set_messages(messages)

    # Legacy flow
    image_queue = Queue()
    emotion_queue = Queue()

    if not args.headless:
        pygame.mixer.init()

    text_processor = TextProcessor()

    # 将角色读音映射注入 text_processor.name_map
    for _char in config.config.characters:
        _pm = getattr(_char, "pronunciation_map", None)
        if _pm:
            from llm.text_processor import name_map
            name_map.update(_pm)

    # 获取背景组
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

    if args.headless and not (args.workflow or "").strip():
        headless_workflow = str(resource_path("assets/system/workflow/headless.yaml"))
    else:
        headless_workflow = None

    workflow = build_runtime_workflow(
        workflow_path=args.workflow or headless_workflow,
        queue_factory=Queue,
    )
    chat_handles = get_chat_workflow_handles(workflow)
    user_input_queue = chat_handles.input_queue
    audio_path_queue = chat_handles.audio_queue
    tts_queue = chat_handles.tts_queue
    _um = chat_handles.ui_worker

    if args.headless:
        from core.runtime.ui_update_manager import HeadlessUIUpdateManager

        ui_updates = HeadlessUIUpdateManager(chat_history=chat_history)
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
            )
        )
        workflow.start()
        print(f"Workflow started: {args.workflow or 'default'}")
        try:
            import time

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            workflow.stop()
            _shutdown_plugins()
            if tts_manager:
                tts_manager.shutdown()
            save_chat_history(args.history, llm_manager.get_messages())
        return

    # Init UI and connect to runtime
    from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from ui.chat_ui.chat_ui import ChatUIWindow
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
        )
    )

    workflow.start()

    init_sprite_path = args.init_sprite_path
    print(init_sprite_path)
    if not init_sprite_path:
        init_sprite_path = str(resource_path("assets/system/picture/shinsekai.png"))

    if system_config_to_asr_lang(config.config.system_config) == "zh":
        _welcome_html = tr_in_bundle("main.welcome_html", "zh_CN")
        _option_start = tr_in_bundle("main.option_start", "zh_CN")
    else:
        _welcome_html = tr_i18n("main.welcome_html")
        _option_start = tr_i18n("main.option_start")
    # 更新初始立绘（已从文件恢复会话时不要先刷欢迎语，否则会 hide 选项区并与恢复队列竞争）
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
        emit_user_text = wire_user_input_plugins(user_input_queue)
    else:
        emit_user_text = None

    # Update system_config with current session's bg/bgm so restore doesn't use stale values
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
                # print(tr_i18n("main.print_bili_import", e=str(e)))
                pass

    # 确保在程序退出时停止所有线程
    try:
        appIcon = QIcon(str(resource_path("assets/system/picture/Icon.png")))
        app.setWindowIcon(appIcon)
    except Exception as e:
        print(tr_i18n("main.print_icon_fail", e=str(e)))

    # ----- 退出流程：独立 try-except 保护保存步骤 -----
    def _safe_save_chat():
        try:
            save_chat_history(args.history, llm_manager.get_messages())
        except Exception:
            logger.exception("保存聊天记录失败", extra={"event": "chat.save.failed"})

    def _safe_save_bg():
        try:
            save_bg(bg_path=window.current_background_path, bgm_path=ui_updates.current_bgm_path)
        except Exception:
            logger.exception("保存背景失败", extra={"event": "bg.save.failed"})

    # 关闭顺序：插件 → TTS 服务器 → Worker 线程 → 保存数据
    app.aboutToQuit.connect(workflow.stop)
    app.aboutToQuit.connect(_shutdown_plugins)
    app.aboutToQuit.connect(lambda: tts_manager and tts_manager.shutdown())
    app.aboutToQuit.connect(_safe_save_chat)
    app.aboutToQuit.connect(_safe_save_bg)
    # -------------------------------------------------

    window.show()

    app.exec()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        handle_main_exception(exc, app_name="Shinsekai Chat", logger=logger)