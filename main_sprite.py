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

from llm.llm_manager import LLMManager
from llm.text_processor import TextProcessor
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
import json
from queue import Queue

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

class LLMWorker(QThread):
    # 发送通知给主UI线程的信号
    update_notification_signal = pyqtSignal(str)

    def __init__(self, llm_manager, user_input_queue: Queue, tts_queue: Queue, parent=None):
        super().__init__(parent)
        self.llm_manager = llm_manager
        self.user_input_queue = user_input_queue
        self.tts_queue = tts_queue
        self.running = True

    def run(self):
        global chat_history
        while self.running:
            try:
                # 从用户输入队列中获取任务，阻塞等待
                message = self.user_input_queue.get()
                if message is None:
                    break
                
                print(f"LLMWorker: 开始处理消息: {message}")
                self.update_notification_signal.emit("正在等待回复中...")

                # 将用户消息添加到历史
                formatted_user_message = f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message}</p>"
                chat_history.append(formatted_user_message)
                
                start_time = time.perf_counter()
                
                # **关键修改点：使用流式模式**
                response_stream = self.llm_manager.chat(message, stream=True)
                
                response_buffer = ""
                content = ""
                
                start_index = 0
                for chunk in response_stream:
                    # 检查是否为完整消息块
                    chunk_message = chunk.choices[0].delta.content
                    response_buffer += chunk_message
                    content += chunk_message

                    while '}' in response_buffer:
                        end_index = response_buffer.find('}') + 1
                        start_index = end_index -1
                        while start_index >=0:
                            if response_buffer[start_index] == '{':
                                break
                            start_index = start_index-1
                        if start_index < 0:
                            break
                        try:
                            json_str = response_buffer[start_index:end_index]
                            print(json_str)

                            dialog_item = json.loads(json_str)
                            self.tts_queue.put(dialog_item)
                            response_buffer = response_buffer[end_index:].strip()

                        except json.JSONDecodeError as e:
                            # 如果解析失败，可能是JSON格式不完整，继续等待更多数据
                            print(f"JSON解析错误，继续等待：{e}")
                            break
                self.llm_manager.add_message("assistant",content)           
                end_time = time.perf_counter()
                
                self.update_notification_signal.emit(f"LLM响应结束，共耗时: {end_time - start_time:.2f} 秒")
                
                self.user_input_queue.task_done()

            except Exception as e:
                print(f"LLMWorker: 任务处理失败: {e}, {start_index}")
                self.user_input_queue.task_done()


class TTSWorker(QThread):
    def __init__(self, tts_manager, tts_queue: Queue, audio_path_queue: Queue, parent=None):
        super().__init__(parent)
        self.tts_manager = tts_manager
        self.tts_queue = tts_queue
        self.audio_path_queue = audio_path_queue
        self.running = True
        self.text_processor = TextProcessor()

    def put_data(self, character_name, speech, sprite, audio_path):
        output_data = {
            'audio_path': audio_path,
            'character_name': character_name,
            'sprite': sprite,
            'speech': speech,
        }
        self.audio_path_queue.put(output_data)
        self.tts_queue.task_done()

    def run(self):
        while self.running:
            try:
                item = self.tts_queue.get()
                if item is None:
                    break

                character_name = item['character_name']
                speech = item['speech']
                translate = item.get('translate','')
                
                if item['sprite'] == '-1':
                   self.put_data(character_name,speech,-1,'')
                   continue

                self.character_config = getCharacter(character_name)
                if self.character_config is None: 
                    continue
                   
                # 生成语音
                speech_text = speech
                text_processor = self.text_processor

                if translate:
                    text_processor = None  # 如果有翻译则不使用文本处理
                    speech_text = translate

                audio_path = ''
                if self.tts_manager:
                    self.tts_manager.switch_model(self.character_config.gpt_model_path, self.character_config.sovits_model_path)
                    audio_path = self.tts_manager.generate_tts(
                        speech_text, 
                        text_processor=text_processor,
                        ref_audio_path=self.character_config.refer_audio_path,
                        prompt_text=self.character_config.prompt_text,
                        prompt_lang=self.character_config.prompt_lang,
                    )
                else:
                    audio_path = self.character_config.sprites[int(item['sprite']) -1].get('voice_path','')
                # 将包含音频路径和原始数据的字典放入音频路径队列
                self.put_data(character_name, speech, item['sprite'], audio_path)

            except Exception as e:
                print(f"TTSWorker: 任务处理失败: {e}")
                self.tts_queue.task_done()


class UIWorker(QThread):
    # 发送给主UI线程的信号
    update_sprite_signal = pyqtSignal(np.ndarray)
    update_dialog_signal = pyqtSignal(str)
    update_notification_signal = pyqtSignal(str)
    
    def __init__(self, audio_path_queue: Queue, parent=None):
        super().__init__(parent)
        self.audio_path_queue = audio_path_queue
        self.running = True

    def run(self):
        global chat_history
        while self.running:
            try:
                # 从音频路径队列中获取数据，阻塞等待
                output_data = self.audio_path_queue.get()
                if output_data is None:
                    break

                character_name = output_data['character_name']
                sprite_id = output_data['sprite']
                speech = output_data['speech']
                audio_path = output_data['audio_path']

                if character_name == "旁白":
                    formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px; color:#84C2D5;'><b>{character_name}</b>：{speech}</p>"
                    chat_history.append(formatted_speech)
                    self.update_dialog_signal.emit(formatted_speech)
                    self.audio_path_queue.task_done()
                    continue

                # 获取角色配置
                character_config = getCharacter(character_name)
                
                if not character_config:
                    print(f"UIWorker: 未找到角色配置: {character_name}")
                    self.audio_path_queue.task_done()
                    continue

                # 更新 UI 通知
                self.update_notification_signal.emit(f"{character_name}正在回复……")

                # 更新立绘
                image_path = character_config.sprites[int(sprite_id) - 1]['path']
                try:
                    cv_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
                    if cv_image is not None:
                        if cv_image.shape[2] == 3:
                            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
                            alpha_channel = np.full((cv_image.shape[0], cv_image.shape[1]), 255, dtype=np.uint8)
                            cv_image = cv2.merge([cv_image, alpha_channel])
                        elif cv_image.shape[2] == 4:
                            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)
                        self.update_sprite_signal.emit(cv_image)
                    else:
                        print(f"UIWorker: 无法加载图片: {image_path}")
                except Exception as e:
                    print(f"UIWorker: 加载图片时出错: {e}")

                # 更新对话框文本
                formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:{character_config.name_color};'>{character_name}</b>：{speech}</p>"
                chat_history.append(formatted_speech)
                self.update_dialog_signal.emit(formatted_speech)

                min_stop_time = len(speech)//8
                start_time = time.perf_counter()
                # 播放音频
                if audio_path:
                    try:
                        pygame.mixer.init()
                        pygame.mixer.music.load(audio_path)
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy():
                            time.sleep(1)
                        pygame.mixer.music.unload()
                    except Exception as e:
                        print(f"UIWorker: 播放音频时出错: {e}")
                end_time = time.perf_counter()
                if end_time - start_time < min_stop_time:
                    time.sleep(min_stop_time - (end_time - start_time))
                
                self.audio_path_queue.task_done()
            
            except Exception as e:
                print(f"UIWorker: 任务处理失败: {e}")
                self.audio_path_queue.task_done()

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

    llm_manager = LLMManager(user_template=user_template, api_key=api_config.get("llm_api_key",""),base_url=api_config.get("llm_base_url",""))

    # 创建图像队列和情感队列
    image_queue = Queue()
    emotion_queue = Queue()

     # 初始化 Pygame
    pygame.mixer.init()

    # 创建三个消息队列
    user_input_queue = Queue()
    tts_queue = Queue()
    audio_path_queue = Queue()

   
    # 创建桌面助手窗口
    app = QApplication([])
    window = DesktopAssistantWindow(image_queue, emotion_queue, llm_manager, sprite_mode=True)

    # 创建并启动 UI Worker 线程
    ui_worker = UIWorker(audio_path_queue)
    ui_worker.update_sprite_signal.connect(window.update_image)
    ui_worker.update_dialog_signal.connect(window.setDisplayWords)
    ui_worker.update_notification_signal.connect(window.setNotification)
    ui_worker.start()
    
    # 创建并启动 TTS Worker 线程
    tts_worker = TTSWorker(tts_manager, tts_queue, audio_path_queue)
    tts_worker.start()

    # 创建并启动 LLM Worker 线程
    llm_worker = LLMWorker(llm_manager, user_input_queue, tts_queue)
    llm_worker.update_notification_signal.connect(window.setNotification)
    llm_worker.start()

    
    # 更新初始立绘
    init_image = cv2.imread('./data/sprite/usami/Danganronpa_V3_Monomi_Bonus_Mode_Sprites_14.webp', cv2.IMREAD_UNCHANGED)
    if init_image is not None:
        if init_image.shape[2] == 3:
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGR2RGB)
            alpha_channel = np.full((init_image.shape[0], init_image.shape[1]), 255, dtype=np.uint8)
            init_image = cv2.merge([init_image, alpha_channel])
        elif init_image.shape[2] == 4:
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGRA2RGBA)
    window.update_image(init_image)
    window.setNotification("和大家开始聊天吧……")
    window.setDisplayWords("<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:#e6b2b2'>兔兔美</b>：欢迎来到新世界程序，希望你和大家能开启love love~的新学期，快和大家聊天吧</p>")

    # 连接 UI 信号到队列
    def on_message_submitted(message):
        user_input_queue.put(message)
        window.setNotification("您的消息已提交，正在等待LLM处理...")
    
    window.message_submitted.connect(lambda message: on_message_submitted(message))
    window.open_chat_history_dialog.connect(lambda: window.open_history_dialog(getHistory()))
    window.change_voice_language.connect(lambda lang: tts_manager.set_language(lang) if tts_manager else None)  
    
    # 确保在程序退出时停止所有线程
    app.aboutToQuit.connect(llm_worker.quit)
    app.aboutToQuit.connect(tts_worker.quit)
    app.aboutToQuit.connect(ui_worker.quit)

    window.show()

    app.exec_()

if __name__ == "__main__":
    main()