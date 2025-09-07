from asyncio import Queue
import sys
import os
from pathlib import Path


# 获取当前脚本的绝对路径
current_script = Path(__file__).resolve()

# 获取项目根目录（main.py所在的目录）
project_root = current_script.parent

# 将项目根目录添加到Python模块搜索路径
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llm.deepseek_sprite import DeepSeek
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QApplication
from tts import tts_manager
from tts.tts_manager import TTSManager
from ui.desktop_ui import DesktopAssistantWindow
from config.character_config import CharacterConfig
import threading
import time
import pygame
import cv2
import numpy as np
import argparse
import yaml

API_CONFIG_PATH = "./data/config/api.yaml"
characters = CharacterConfig.read_from_files('./data/config/characters.yaml')
api_config = {
    "llm_api_key": "",
    "llm_base_url": "",
    "gpt_sovits_url": "",
    "gpt_sovits_api_path":""
}
voice_lang = "ja"
chat_history = []

def load_api_config_from_file():
    global api_config
    try:
        with open(API_CONFIG_PATH, 'r', encoding='utf-8') as f:
            api_config = yaml.safe_load(f) or {}
        return "API配置已加载！"
    except Exception as e:
        return f"加载失败: {str(e)}"

def getCharacter(name):
    for character in characters:
        if character.name == name:
            return character
    return None

class ChatWorker(QThread):
    """后台聊天工作线程"""
    update_dialog_signal = pyqtSignal(str)
    update_notification_signal = pyqtSignal(str)
    update_sprite_signal = pyqtSignal(np.ndarray)
    def __init__(self, deepseek, message, tts_manager: TTSManager = None):
        """初始化工作线程"""
        super().__init__()
        self.deepseek = deepseek
        self.message = message
        self.response_list = []
        self.tts_manager = tts_manager
        self.running = True
        self.daemon = True  # 设置为守护线程
      
        self.sprite_prefix = './data/sprite/Danganronpa_V3_Nagito_Komaeda_Bonus_Mode_Sprites_'  # 立绘图片的前缀路径
        self.character_config = getCharacter('狛枝凪斗')
    
    def run(self):
        """在后台线程中执行聊天请求"""
        global chat_history
        print(f"Deepseek处理消息: {self.message}")
        
        start_time = time.perf_counter()
        dialog = self.deepseek.chat(self.message)
        end_time = time.perf_counter()
        print(f"Deepseek响应时间: {end_time - start_time:.2f} 秒")
        chat_history.append(f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {self.message}</p>")
        self.response_list = dialog if isinstance(dialog, list) else []
        if not self.response_list:
            return

        self.update_notification_signal.emit(f"经过{end_time - start_time:.2f}秒收到{len(self.response_list)}条回复，正在合成语音喵……")

        for i, item in enumerate(self.response_list):
            if not self.running:
                break
                
            # 提取character_name, sprite和speech
            character_name = item.get('character_name', '狛枝凪斗')
            sprite = item.get('sprite', 'default')
            speech = item.get('speech', '')
            translate = item.get('translate', '')
        
            # 处理旁白
            if character_name == '旁白':
                formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px; color:#84C2D5;'><b style='color:#84C2D5;'>{character_name}</b>：{speech}</p>"
                chat_history.append(formatted_speech)
                self.update_dialog_signal.emit(formatted_speech)
                self.update_notification_signal.emit(f"收到消息 {i+1}/{len(self.response_list)}")
                sleep_span = len(speech) // 8
                if sleep_span < 4:
                    sleep_span = 4
                time.sleep(sleep_span)
                continue

            self.character_config = getCharacter(character_name)
            if not self.character_config:
                print(f"未找到角色配置: {character_name}")
                continue

            if not sprite:
                continue
            should_sleep = True
            self.sprite_prefix = self.character_config.sprite_prefix
            sprite_id = int(sprite)
            audio_path = None
            if not self.tts_manager:
                if self.character_config.sprites[sprite_id-1].get('voice_path',''):
                    audio_path = self.character_config.sprites[sprite_id-1]['voice_path']
            else:
                # 切换模型
                self.tts_manager.switch_model(self.character_config.gpt_model_path, self.character_config.sovits_model_path)
                # 生成音频
                self.update_notification_signal.emit(f"{character_name}正在准备回复……")
                text_processor = self.deepseek.text_processor
                speech_text = speech
                if translate:
                    text_processor = None  # 如果有翻译则不使用文本处理
                    speech_text = translate
                audio_path = self.tts_manager.generate_tts(
                    speech_text, 
                    text_processor=text_processor,
                    ref_audio_path=self.character_config.refer_audio_path,
                    prompt_text=self.character_config.prompt_text,
                    prompt_lang=self.character_config.prompt_lang,
                    character_name=character_name
                )
                if audio_path:
                    should_sleep = False
            # 更新角色立绘
           
            image_path = self.character_config.sprites[sprite_id-1]['path']
            try:
                # 使用 OpenCV 读取图像
                cv_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
                
                if cv_image is not None:
                    # 转换颜色格式 BGR -> RGBA
                    if cv_image.shape[2] == 3:  # RGB 图像
                        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
                        # 添加 alpha 通道
                        alpha_channel = np.full((cv_image.shape[0], cv_image.shape[1]), 255, dtype=np.uint8)
                        cv_image = cv2.merge([cv_image, alpha_channel])
                    elif cv_image.shape[2] == 4:  # RGBA 图像
                        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)
                    
                    self.update_sprite_signal.emit(cv_image)  # 发出更新立绘的信号
                    
                else:
                    print(f"无法加载图片: {image_path}")
            except Exception as e:
                print(f"加载图片时出错: {e}")

            # 更新对话框文字
            formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:{self.character_config.name_color};'>{character_name}</b>：{speech}</p>"
            chat_history.append(formatted_speech)
            self.update_dialog_signal.emit(formatted_speech)
            self.update_notification_signal.emit(f"收到消息 {i+1}/{len(self.response_list)}")

            # 播放语音
            if audio_path:
                try:
                    pygame.mixer.init()
                    pygame.mixer.music.load(audio_path)
                    pygame.mixer.music.play()

                    # 等待音频播放完成
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.1)
                    
                    # 释放音频资源
                    pygame.mixer.music.unload()
                except Exception as e:
                    print(f"播放音频时出错: {e}")

            if should_sleep:
                sleep_span = len(speech) // 8
                if sleep_span < 4:
                    sleep_span = 4
                time.sleep(sleep_span)

def handleResponse(deepseek, message, tts_manager=None, desktop_ui=None):    
    global api_config
    """处理聊天响应"""
    print(f"处理消息: {message}")
    thread = ChatWorker(deepseek, message, tts_manager)
    if desktop_ui:
        thread.update_dialog_signal.connect(desktop_ui.setDisplayWords)
        thread.update_sprite_signal.connect(desktop_ui.update_image)
        thread.update_notification_signal.connect(desktop_ui.setNotification)
        print("连接信号到桌面UI")
    else:
        print("Desktop UI未提供，无法更新界面")
    threading.Thread(target=thread.run).start()

def getHistory():   
    """获取聊天历史记录"""
    return chat_history

def main():
    load_api_config_from_file()
    parser = argparse.ArgumentParser(description='示例脚本')
    # 添加参数
    parser.add_argument('--template', '-t', type=str, help='用户模板名称', default='komaeda_sprite')
    parser.add_argument('--voice_mode', '-v', type=str, default='gen')

    # 解析参数
    args = parser.parse_args()

    # 创建TTS管理器实例
    tts_manager = None
    if args.voice_mode == 'gen':
        tts_manager = TTSManager(tts_server_url=api_config.get("gpt_sovits_url",""))
        try:
            tts_manager.load_tts_model(gpt_sovits_work_path=api_config.get("gpt_sovits_api_path",""))
        except Exception as e:
            tts_manager=None
            print("语音模块加载失败", e)
    
    # 创建DeepSeek实例
    print("加载用户模板...", args)

    user_template = ""
    with open(f'./data/character_templates/{args.template}.txt', 'r', encoding='utf-8') as f:
        user_template = f.read()
    print("Loaded user template:")
    print(user_template)

    deepseek = DeepSeek(user_template=user_template, api_key=api_config.get("llm_api_key",""),base_url=api_config.get("llm_base_url",""))

    # 创建图像队列和情感队列
    image_queue = Queue()
    emotion_queue = Queue()

    # 创建桌面助手窗口
    app = QApplication([])
    window = DesktopAssistantWindow(image_queue, emotion_queue, deepseek, sprite_mode=True)
    init_image = cv2.imread('./data/sprite/usami/Danganronpa_V3_Monomi_Bonus_Mode_Sprites_14.webp', cv2.IMREAD_UNCHANGED)
    if init_image is not None:
        # 转换颜色格式 BGR -> RGBA
        if init_image.shape[2] == 3:  # RGB 图像
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGR2RGB)
            # 添加 alpha 通道
            alpha_channel = np.full((init_image.shape[0], init_image.shape[1]), 255, dtype=np.uint8)
            init_image = cv2.merge([init_image, alpha_channel])
        elif init_image.shape[2] == 4:  # RGBA 图像
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGRA2RGBA)
    window.update_image(init_image)  # 设置初始图像
    window.setNotification("和大家开始聊天吧……")
    window.setDisplayWords("<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:#e6b2b2'>兔兔美</b>：欢迎来到新世界程序，希望你和大家能开启love love~的新学期，快和大家聊天吧</p>")

    window.message_submitted.connect(lambda message: handleResponse(deepseek, message, tts_manager, window))
    window.open_chat_history_dialog.connect(lambda: window.open_history_dialog(getHistory()))
    window.change_voice_language.connect(lambda lang: tts_manager.set_language(lang) if tts_manager else None)

    window.show()

    app.exec_()

if __name__ == "__main__":
    main()