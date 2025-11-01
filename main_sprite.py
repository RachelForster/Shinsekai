from asyncio import Queue
import os
from pathlib import Path

import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llm.llm_manager import LLMManager,LLMAdapterFactory
from llm.history_manager import HistoryManager
from core.workers import LLMWorker, TTSWorker, UIWorker
from core.message import UserInputMessage, LLMDialogMessage, TTSOutputMessage
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QApplication
from tts.tts_manager import TTSManager, TTSAdapterFactory
from ui.desktop_ui import DesktopAssistantWindow
from config.character_config import CharacterConfig
from config.config_manager import ConfigManager
import threading
import time
import pygame
import cv2
import numpy as np
from opencc import OpenCC
import argparse
import yaml
import json
from queue import Queue
import traceback

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

def main():
    global chat_history
    config = ConfigManager()
    parser = argparse.ArgumentParser(description='示例脚本')
    # 添加参数
    parser.add_argument('--template', '-t', type=str, help='用户模板名称', default='komaeda_sprite')
    parser.add_argument('--voice_mode', '-v', type=str, default='gen')
    parser.add_argument('--init_sprite_path', '-isp', type=str, default='')
    parser.add_argument('--history','--his',type=str, default='')
    parser.add_argument('--tts',type=str,default="gpt-sovits")
    parser.add_argument('--llm',type=str,default="deepseek")
    parser.add_argument('--bg', type=str,default='')

    # 解析参数
    args = parser.parse_args()

    # 创建TTS管理器实例
    tts_manager = None
    if args.voice_mode == 'gen':
        gsv_url, gsv_api_path = config.get_gpt_sovits_config()
        adapter = TTSAdapterFactory.create_adapter(
            adapter_name=args.tts,
            gpt_sovits_work_path=gsv_api_path
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
    llm_manager = LLMManager(adapter=llm_adapter,user_template=user_template)

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
    window = DesktopAssistantWindow(image_queue, emotion_queue, llm_manager, sprite_mode=True, background_mode=(bg_group!=None))

    # 创建并启动 UI Worker 线程
    ui_worker = UIWorker(audio_path_queue, chat_history=chat_history,bg_group=bg_group)
    ui_worker.update_sprite_signal.connect(window.update_image)
    ui_worker.update_dialog_signal.connect(window.setDisplayWords)
    ui_worker.update_notification_signal.connect(window.setNotification)
    ui_worker.update_option_signal.connect(window.setOptions)
    ui_worker.update_value_signal.connect(window.update_numeric_info)
    ui_worker.update_bg.connect(window.setBackgroundImage)
    ui_worker.start()
    
    # 创建并启动 TTS Worker 线程
    tts_worker = TTSWorker(tts_manager, tts_queue, audio_path_queue, bgm_list=bgm_list)
    tts_worker.start()

    # 创建并启动 LLM Worker 线程
    llm_worker = LLMWorker(llm_manager, user_input_queue, tts_queue, chat_history=chat_history)
    llm_worker.update_notification_signal.connect(window.setNotification)
    llm_worker.start()

    init_sprite_path = args.init_sprite_path
    print (init_sprite_path)
    if not init_sprite_path:
        init_sprite_path = './assets/system/picture/shinsekai.png'

    # 更新初始立绘
    try:
        # init_image = cv2.imread(init_sprite_path, cv2.IMREAD_UNCHANGED)
        # if init_image is not None:
        #     if init_image.shape[2] == 3:
        #         init_image = cv2.cvtColor(init_image, cv2.COLOR_BGR2RGB)
        #         alpha_channel = np.full((init_image.shape[0], init_image.shape[1]), 255, dtype=np.uint8)
        #         init_image = cv2.merge([init_image, alpha_channel])
        #     elif init_image.shape[2] == 4:
        #         init_image = cv2.cvtColor(init_image, cv2.COLOR_BGRA2RGBA)
        window.setBackgroundImage('./assets/system/picture/shinsekai.png')
        window.setDisplayWords("<p style='line-height: 135%; letter-spacing: 2px;'>欢迎来到新世界程序，开始聊天吧！这是个初始立绘和对话。输入消息，你的角色就会出现。</p>")

        if len(getHistory()) <= 1:
            window.setOptions(['开始'])
    except Exception as e:
        # print("更新初始立绘失败",e)
        # init_image = np.zeros((512, 512, 4), dtype=np.uint8)
        # window.update_image(init_image)
        window.setDisplayWords("<p style='line-height: 135%; letter-spacing: 2px;'>欢迎来到新世界程序，开始聊天吧！这是个初始立绘和对话。输入消息，你的角色就会出现。</p>")
    window.setNotification("开始聊天吧……")
    # 连接 UI 信号到队列
    def on_message_submitted(message):
        print("已提交：", message)
        user_input_queue.put(UserInputMessage(text=message))
        window.setNotification("您的消息已提交，正在等待LLM处理...")
    
    # 恢复最后一条消息
    if messages:
        try:
            msg = ''
            while messages and messages[-1]['role'] == 'user':
                messages.pop()
            msg = messages[-1]['content']
            print(msg)
            if messages and messages[-1]['role'] == 'system':
                raise ValueError("没有任何LLM发送的历史消息！")
            dialog = json.loads(msg)['dialog']
            while dialog and (dialog[-1].get("sprite",'-1') == '-1' or dialog[-1].get("sprite",'-1') == -1): 
                audio_path_queue.put(TTSOutputMessage(
                    audio_path='',
                    character_name=dialog[-1].get('character_name',''),
                    speech=dialog[-1].get('speech'),
                    sprite='-1',
                    is_system_message=True
                ))
                dialog.pop()
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
  
    window.message_submitted.connect(lambda message: on_message_submitted(message))
    window.open_chat_history_dialog.connect(lambda: window.open_history_dialog(chat_history))
    window.change_voice_language.connect(lambda lang: tts_manager.set_language(lang) if tts_manager else None)
    window.close_window.connect(app.quit)
    window.clear_chat_history.connect(lambda: clear_chat_history(history_file=args.history, ui_queue=audio_path_queue, llm_manager=llm_manager))
    window.skip_speech_signal.connect(lambda: ui_worker.skip_speech())
    
    # 确保在程序退出时停止所有线程
    app.aboutToQuit.connect(llm_worker.quit)
    app.aboutToQuit.connect(tts_worker.quit)
    app.aboutToQuit.connect(ui_worker.quit)
    app.aboutToQuit.connect(lambda :save_chat_history(args.history,llm_manager.get_messages()))

    window.show()

    app.exec_()

if __name__ == "__main__":
    main()