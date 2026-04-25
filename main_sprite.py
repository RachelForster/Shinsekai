from asyncio import Queue
import os
from pathlib import Path

import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))
import llm.tools.character_tools
from llm.llm_manager import LLMManager,LLMAdapterFactory
from llm.history_manager import HistoryManager
from core.workers import LLMWorker, TTSWorker, UIWorker
from core.ui_update_manager import UIUpdateManager, connect_to_desktop_window
from core.message import UserInputMessage, LLMDialogMessage, TTSOutputMessage
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage, QIcon
from PyQt5.QtWidgets import QApplication
from tts.tts_manager import TTSManager, TTSAdapterFactory
from ui.desktop_ui import DesktopAssistantWindow
from config.character_config import CharacterConfig
from config.config_manager import ConfigManager
from t2i.t2i_manager import T2IAdapterFactory, T2IManager
import threading
import time
import pygame
import cv2
import numpy as np
from opencc import OpenCC
import argparse
import yaml
import json
import re
from queue import Queue
import traceback
try:
    from live.danmuku_handler import start_bilibili_service
except ImportError as e:
    print(f"导入Bilibili服务失败: {e}")

CHAT_HISTORY_PATH = "./data/chat_history"

voice_lang = "ja"
cc = OpenCC('t2s')  # 繁体到简体转换器
chat_history = []
history_manager = HistoryManager(chat_history)

def getHistory():   
    """获取聊天历史记录"""
    return history_manager.get_history()

def save_chat_history(file_path, history):
    """根据提供的文件名保存聊天记录到 JSON 文件。"""
    history_manager.save_chat_history(file_path, history)

def load_chat_history(file_path):
    return history_manager.load_chat_history(file_path)

def clear_chat_history(history_file, ui_queue, llm_manager):
    history_manager.clear_chat_history(history_file)

    llm_manager.clear_messages()

    ui_queue.put(TTSOutputMessage(
        audio_path="",
        character_name="系统",
        speech="历史记录已经清空",
        sprite='-1',
        is_system_message=False
    ))

def copy_chat_history_to_clipboard():
    """将聊天记录复制到系统剪贴板，去除 HTML 标签并格式化为纯文本。"""
    history_manager.copy_chat_history_to_clipboard()

def replay_history_entry(window, history_entry: str):
    """回放一条历史记录。若为选项则重新显示选项。"""
    if not history_entry:
        return

    plain_text = re.sub(r"<[^>]+>", "", history_entry).strip()
    name = ""
    content = plain_text
    if "：" in plain_text:
        name, content = plain_text.split("：", 1)
    elif ":" in plain_text:
        name, content = plain_text.split(":", 1)

    if name.strip() == "选项":
        option_list = [item.strip() for item in content.split("/") if item.strip()]
        window.setOptions(option_list)
        # window.setNotification("已回溯到选项，请重新选择")
    else:
        window.setDisplayWords(history_entry)
        # window.setNotification("已回溯该条记录")

def is_option_history_entry(history_entry: str) -> bool:
    if not isinstance(history_entry, str):
        return False
    plain_text = re.sub(r"<[^>]+>", "", history_entry).strip()
    return plain_text.startswith("选项：") or plain_text.startswith("选项:")

def is_user_history_entry(history_entry: str) -> bool:
    if not isinstance(history_entry, str):
        return False
    return "你</b>" in history_entry or "你</b>：" in history_entry or "你</b>:" in history_entry

def extract_valid_dialog_from_messages(messages: list) -> list:
    """从历史消息中提取最后一条可用 assistant dialog。"""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        if not content:
            continue
        try:
            parsed = json.loads(content)
            dialog = parsed.get("dialog", [])
            if isinstance(dialog, list) and dialog:
                return dialog
        except Exception:
            continue
    return []

def revert_chat_history(user_index: int, llm_manager, chat_history, window):
    """按 user_index 回溯到该用户消息之前的上一条 assistant 记录。"""
    if user_index < 0:
        return

    # 1) 找到第 user_index 条用户消息在 chat_history 中的位置
    current_user_idx = -1
    user_history_pos = -1
    for idx, entry in enumerate(chat_history):
        if is_user_history_entry(entry):
            current_user_idx += 1
            if current_user_idx == user_index:
                user_history_pos = idx
                break

    if user_history_pos == -1:
        return

    # 2) 回溯目标是该用户消息之前最近的一条非 user 记录（通常是 assistant/选项）
    target_index = -1
    for idx in range(user_history_pos - 1, -1, -1):
        if not is_user_history_entry(chat_history[idx]):
            target_index = idx
            break

    if target_index < 0:
        return

    # 3) 裁剪 UI 聊天历史（原地修改，保持引用不变）
    del chat_history[target_index + 1:]

    messages = llm_manager.get_messages()
    if not messages:
        return

    # 4) 简化：LLM 消息仅保留到 user_index 之前。
    # 也就是遇到第 user_index 条 user 消息时停止，不包含该 user 及其后续消息。
    new_messages = []
    current_user_idx = -1
    for message in messages:
        role = message.get("role")
        if role == "user":
            current_user_idx += 1
            if current_user_idx >= user_index:
                break
        new_messages.append(message)

    llm_manager.set_messages(new_messages)

    if chat_history:
        replay_history_entry(window, chat_history[-1])

def save_bg(bg_path, bgm_path):
    config = ConfigManager()
    config.config.system_config.background_path = bg_path
    config.config.system_config.bgm_path = bgm_path
    config.save_system_config()

def main():
    global chat_history
    config = ConfigManager()
    parser = argparse.ArgumentParser(description='示例脚本')
    # 添加参数
    parser.add_argument('--template', '-t', type=str, help='用户模板名称', default='komaeda_sprite')
    parser.add_argument('--voice_mode', '-v', type=str, default='gen')
    parser.add_argument('--init_sprite_path', '-isp', type=str, default='')
    parser.add_argument('--history','--his',type=str, default='')
    parser.add_argument('--tts',type=str,default="")
    parser.add_argument('--llm',type=str,default="deepseek")
    parser.add_argument('--bg', type=str,default='')
    parser.add_argument('--t2i',type=str,default='ComfyUI')
    parser.add_argument('--room_id', type=str, default='', help='bilibili live room id')

    # 解析参数
    args = parser.parse_args()

    # T2I manager
    t2i_manager=None
    if args.t2i:
        try: 
            t2i_adapter=T2IAdapterFactory.create_adapter(adapter_name=args.t2i,
                                                        work_path=config.config.api_config.t2i_work_path,
                                                        api_url=config.config.api_config.t2i_api_url, 
                                                        workflow_path=config.config.api_config.t2i_default_workflow_path,
                                                        prompt_node_id=config.config.api_config.t2i_prompt_node_id, 
                                                        output_node_id=config.config.api_config.t2i_output_node_id
                                                        )
            t2i_manager = T2IManager(t2i_adapter)
        except Exception as e:
            print(f"T2I manager初始化失败{e}")
            traceback.print_exc()

    # 创建TTS管理器实例
    tts_manager = None
    if args.voice_mode == 'gen':
        gsv_url, gsv_api_path, config_tts_provider = config.get_gpt_sovits_config()
        adapter_name = args.tts if args.tts else config_tts_provider
        adapter = TTSAdapterFactory.create_adapter(
            adapter_name=adapter_name,
            gpt_sovits_work_path=gsv_api_path,
            tts_server_url=gsv_url
        )
        tts_manager = TTSManager(tts_server_url=gsv_url)
        tts_manager.set_tts_adapter(adapter=adapter)
    
    
    # 创建DeepSeek实例
    print("加载用户模板...", args)

    messages = []
    if args.history:
        print("加载历史记录...", args.history)
        messages = load_chat_history(args.history)


    user_template = ""
    with open(f'./data/character_templates/{args.template}.txt', 'r', encoding='utf-8') as f:
        user_template = f.read()

    llm_provider, llm_model, base_url, api_key = config.get_llm_api_config()
    print(llm_provider, llm_model, base_url, api_key)
    if not llm_provider:
        print("请选择大语言模型供应商")
        return
    llm_adapter = LLMAdapterFactory.create_adapter(llm_provider=llm_provider, api_key=api_key, base_url=base_url, model = llm_model)
    llm_manager = LLMManager(
        adapter=llm_adapter,
        user_template=user_template,
        max_tokens=int(config.config.api_config.max_context_tokens),
        generation_config={
            "temperature": float(config.config.api_config.temperature),
            "repetition_penalty": float(config.config.api_config.repetition_penalty),
            "presence_penalty": float(config.config.api_config.presence_penalty),
            "frequency_penalty": float(config.config.api_config.frequency_penalty),
            # 作为单轮输出上限而非上下文上限，给一个温和值
            "max_tokens": 4096
        }
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
    
    # 获取背景组
    bg_group = None
    try:
        bg_group = None if args.bg is None or args.bg == "透明背景" else config.get_background_by_name(args.bg).sprites
    except Exception as e:
        pass

    bgm_list = []
    try:
        bgm_list = [] if args.bg is None or args.bg == "透明背景" else config.get_background_by_name(args.bg).bgm_list
    except Exception as e:
        pass
    # 创建桌面助手窗口
    app = QApplication([])
    ui_updates = UIUpdateManager()
    window = DesktopAssistantWindow(image_queue, emotion_queue, llm_manager, sprite_mode=True, background_mode=(bg_group!=None))
    connect_to_desktop_window(ui_updates, window)

    # 创建并启动 UI Worker 线程
    ui_worker = UIWorker(
        audio_path_queue,
        ui_updates,
        chat_history=chat_history,
        bg_group=bg_group,
    )
    ui_worker.start()
    
    # 创建并启动 TTS Worker 线程
    tts_worker = TTSWorker(tts_manager,t2i_manager, tts_queue, audio_path_queue, bgm_list=bgm_list)
    tts_worker.start()

    # 创建并启动 LLM Worker 线程
    llm_worker = LLMWorker(
        llm_manager,
        user_input_queue,
        tts_queue,
        ui_updates,
        chat_history=chat_history,
    )
    llm_worker.start()

    init_sprite_path = args.init_sprite_path
    print (init_sprite_path)
    if not init_sprite_path:
        init_sprite_path = './assets/system/picture/shinsekai.png'

    _welcome_html = (
        "<p style='line-height: 135%; letter-spacing: 2px;'>欢迎来到新世界程序，开始聊天吧！"
        "这是个初始立绘和对话。输入消息，你的角色就会出现。</p>"
    )
    # 更新初始立绘（已从文件恢复会话时不要先刷欢迎语，否则会 hide 选项区并与恢复队列竞争）
    try:
        if not messages:
            window.setDisplayWords(_welcome_html)
            if len(getHistory()) <= 1:
                window.setOptions(["开始"])
    except Exception:
        if not messages:
            window.setDisplayWords(_welcome_html)
    window.setNotification("开始聊天吧……")
    # 连接 UI 信号到队列
    def on_message_submitted(message):
        print("已提交：", message)
        user_input_queue.put(UserInputMessage(text=message))
        window.setNotification("您的消息已提交，正在等待LLM处理...")
    
    # 恢复最后一条消息
    if messages:
        try:
            dialog = extract_valid_dialog_from_messages(messages)
            if not dialog:
                raise ValueError("没有可恢复的有效 assistant dialog")
            # 末尾连续 sprite=-1 的系统句（旁白、选项等）从列表尾部弹出，但入队须按对话时间正序。
            # 否则先入队「选项」再入队更早的旁白时，UIWorker 里后者的 setDisplayWords 会盖住选项。
            trailing_system: list = []
            while dialog and (
                dialog[-1].get("sprite", "-1") == "-1" or dialog[-1].get("sprite", "-1") == -1
            ):
                trailing_system.append(dialog.pop())
            for item in reversed(trailing_system):
                audio_path_queue.put(
                    TTSOutputMessage(
                        audio_path="",
                        character_name=item.get("character_name", ""),
                        speech=item.get("speech"),
                        sprite="-1",
                        is_system_message=True,
                    )
                )
            if dialog:
                # 只更新立绘
                audio_path_queue.put(
                    TTSOutputMessage(
                        audio_path='',
                        character_name=dialog[-1].get('character_name',''),
                        speech='',
                        sprite=dialog[-1].get('sprite','-1'),
                        is_system_message=False
                    )
                )
        except Exception as e:
            traceback.print_exc()
            print('最后一条消息更新失败', e)


        try:
            bgm_path = config.config.system_config.bgm_path
            bg_path = config.config.system_config.background_path
            if bgm_path:
                audio_path_queue.put(
                    TTSOutputMessage(
                        audio_path=bgm_path,
                        character_name="bgm",
                        sprite="-1",
                        is_system_message=True
                    )
                )
            if bg_path:
                window.setBackgroundImage(bg_path)
        except Exception as e:
            print("更新背景和bgm失败",e)
            traceback.print_exc()
  
    window.message_submitted.connect(lambda message: on_message_submitted(message))
    window.open_chat_history_dialog.connect(lambda: window.open_history_dialog(chat_history))
    window.change_voice_language.connect(lambda lang: tts_manager.set_language(lang) if tts_manager else None)
    window.close_window.connect(app.quit)
    window.clear_chat_history.connect(lambda: clear_chat_history(history_file=args.history, ui_queue=audio_path_queue, llm_manager=llm_manager))
    window.skip_speech_signal.connect(lambda: ui_worker.skip_speech())
    window.copy_chat_history_to_clipboard.connect(lambda: copy_chat_history_to_clipboard())
    window.revert_chat_history.connect(
        lambda index: revert_chat_history(
            user_index=index,
            llm_manager=llm_manager,
            chat_history=chat_history,
            window=window
        )
    )

    if args.room_id:
        print("启动B站直播弹幕监听，房间ID:", args.room_id)
        try:
            start_bilibili_service(args.room_id, user_input_queue=user_input_queue)
        except ImportError as e:
            print(f"导入Bilibili服务失败: {e}")

    # 确保在程序退出时停止所有线程
    try:
        appIcon = QIcon('./assets/system/picture/icon.png')
        app.setWindowIcon(appIcon)
    except Exception as e:
        print("设置窗口图标失败", e)
    app.aboutToQuit.connect(llm_worker.quit)
    app.aboutToQuit.connect(tts_worker.quit)
    app.aboutToQuit.connect(ui_worker.quit)
    app.aboutToQuit.connect(lambda :save_chat_history(args.history,llm_manager.get_messages()))
    app.aboutToQuit.connect(lambda :save_bg(bg_path=window.current_background_path,bgm_path=ui_worker.current_bgm_path))

    window.show()

    app.exec_()

if __name__ == "__main__":
    main()