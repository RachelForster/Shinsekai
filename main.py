import os
from pathlib import Path
import sys

# 打包后须在任何会触发 ConfigManager 的 import 之前设发行根 cwd（同 webui_qt）
if getattr(sys, "frozen", False):
    try:
        _rel = Path(sys.executable).resolve().parent.parent
        os.environ["EASYAI_PROJECT_ROOT"] = str(_rel)
        os.chdir(_rel)
    except OSError:
        pass

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

if getattr(sys, "frozen", False):
    from core.bootstrap.frozen_log import init_frozen_stdio

    init_frozen_stdio("main")

import llm.tools.character_tools
import llm.tools.memory_tools
from llm.template_generator import is_transparent_background
from llm.llm_manager import LLMManager, LLMAdapterFactory
from llm.text_processor import TextProcessor
from core.runtime.workers import LLMWorker, TTSWorker, UIWorker
from core.runtime.app_runtime import AppRuntime, set_app_runtime
from core.runtime.ui_update_manager import UIUpdateManager, connect_to_desktop_window
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from tts.tts_manager import TTSManager, TTSAdapterFactory
from ui.chat_ui.chat_ui import ChatUIWindow
from ui.chat_ui.qss_fusion import ensure_fusion_style
from config.config_manager import ConfigManager
from t2i.t2i_manager import T2IAdapterFactory, T2IManager
import pygame
import traceback
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
from core.sprite.sprite_cli import parse_sprite_args
try:
    from live.danmuku_handler import start_bilibili_service
except ImportError as e:
    # 早于 init_i18n，不调用 tr
    print("Bilibili import failed:", e)

voice_lang = "ja"
cc = OpenCC("t2s")  # 繁体到简体转换器


def main():
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
        except Exception as e:
            print(tr_i18n("main.print_t2i_fail", e=str(e)))
            traceback.print_exc()

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
        except Exception as e:
            print(tr_i18n("main.print_tts_fail", e=str(e)))
            traceback.print_exc()

    # 创建DeepSeek实例
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

    llm_provider, llm_model, base_url, api_key = config.get_llm_api_config()
    print(llm_provider, llm_model, base_url, api_key)
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
        generation_config={
            "temperature": float(config.config.api_config.temperature),
            "repetition_penalty": float(config.config.api_config.repetition_penalty),
            "presence_penalty": float(config.config.api_config.presence_penalty),
            "frequency_penalty": float(config.config.api_config.frequency_penalty),
            "max_tokens": 4096,
        },
    )

    if messages:
        llm_manager.set_messages(messages)

    # 创建图像队列和情感队列
    image_queue = Queue()
    emotion_queue = Queue()

    # 初始化 Pygame
    pygame.mixer.init()

    # 创建三个消息队列
    user_input_queue = Queue()
    tts_queue = Queue()
    audio_path_queue = Queue()

    text_processor = TextProcessor()

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
    # 创建桌面助手窗口
    app = QApplication([])
    ensure_fusion_style(app)
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

    # 创建并启动 Worker 线程（队列显式连接流水线，其馀从 app_runtime 注入）
    ui_worker = UIWorker(audio_path_queue)
    ui_worker.start()

    tts_worker = TTSWorker(tts_queue, audio_path_queue)
    tts_worker.start()

    llm_worker = LLMWorker(user_input_queue, tts_queue)
    llm_worker.start()

    init_sprite_path = args.init_sprite_path
    print(init_sprite_path)
    if not init_sprite_path:
        init_sprite_path = "./assets/system/picture/shinsekai.png"

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

    emit_user_text = wire_user_input_plugins(user_input_queue)

    chat_ui_ctx = install_chat_ui_context(window, emit_user_text=emit_user_text)

    restore_session_ui(
        messages,
        audio_path_queue=audio_path_queue,
        window=window,
        config=config,
        tr_i18n=tr_i18n,
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
        ui_worker=ui_worker,
        tr_i18n=tr_i18n,
    )

    if args.room_id:
        print(tr_i18n("main.print_bili_start", id=args.room_id))
        try:
            start_bilibili_service(args.room_id, user_input_queue=user_input_queue)
        except ImportError as e:
            print(tr_i18n("main.print_bili_import", e=str(e)))

    # 确保在程序退出时停止所有线程
    try:
        appIcon = QIcon("./assets/system/picture/icon.png")
        app.setWindowIcon(appIcon)
    except Exception as e:
        print(tr_i18n("main.print_icon_fail", e=str(e)))

    app.aboutToQuit.connect(llm_worker.quit)
    app.aboutToQuit.connect(tts_worker.quit)
    app.aboutToQuit.connect(ui_worker.quit)
    try:
        from core.plugins.plugin_host import get_plugin_manager

        mgr = get_plugin_manager()

        def _shutdown_plugins() -> None:
            if mgr is not None:
                try:
                    mgr.shutdown_all()
                except Exception:
                    pass

        app.aboutToQuit.connect(_shutdown_plugins)
    except Exception:
        pass
    app.aboutToQuit.connect(lambda: save_chat_history(args.history, llm_manager.get_messages()))
    app.aboutToQuit.connect(
        lambda: save_bg(
            bg_path=window.current_background_path,
            bgm_path=ui_updates.current_bgm_path,
        )
    )

    window.show()

    app.exec()


if __name__ == "__main__":
    main()
