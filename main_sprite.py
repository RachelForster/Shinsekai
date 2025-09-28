from asyncio import Queue
import os
from pathlib import Path

import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llm.llm_manager import LLMManager,LLMAdapterFactory
from llm.text_processor import TextProcessor
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QApplication
from tts.tts_manager import TTSManager, TTSAdapterFactory
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
CHAT_HISTORY_PATH = "./data/chat_history"
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

def getCharacterScale(character_name: str):
    if character_name is None:
        return 1.0
    character = getCharacter(character_name)
    if character is None:
        return 1.0
    return character.sprite_scale


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
                self.update_notification_signal.emit("发送成功，正在等待回复中...")

                # 将用户消息添加到历史
                formatted_user_message = f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message}</p>"
                chat_history.append(formatted_user_message)
                
                start_time = time.perf_counter()
                
                response_stream = self.llm_manager.chat(message, stream=True)
                
                response_buffer = ""
                content = ""
                
                start_index = 0
                for chunk in response_stream:
                    # 检查是否为完整消息块
                    chunk_message = chunk.choices[0].delta.content
                    if chunk_message:
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
                print("LLM worker get an item")
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
                    model_info ={
                        'sovits_model_path': self.character_config.sovits_model_path, 
                        'gpt_model_path': self.character_config.gpt_model_path,
                    }
                    self.tts_manager.switch_model(model_info)

                    sprite_id = int(item["sprite"]) -1
                    ref_audio_path = self.character_config.refer_audio_path
                    prompt_text = self.character_config.prompt_text
                    if self.character_config.sprites[sprite_id].get("voice_text",None):
                        ref_audio_path = Path(self.character_config.sprites[sprite_id].get("voice_path")).absolute()
                        ref_audio_path = str(ref_audio_path)
                        prompt_text = self.character_config.sprites[sprite_id].get("voice_text")
                    audio_path = self.tts_manager.generate_tts(
                        speech_text, 
                        text_processor=text_processor,
                        ref_audio_path=ref_audio_path,
                        prompt_text=prompt_text,
                        prompt_lang=self.character_config.prompt_lang,
                        character_name=character_name,
                    )
                else:
                    audio_path = self.character_config.sprites[int(item['sprite']) -1].get('voice_path','')
                # 将包含音频路径和原始数据的字典放入音频路径队列
                self.put_data(character_name, speech, item['sprite'], audio_path)
                print(f'TTSWorker put: {audio_path} into the UI queue')

            except Exception as e:
                print(f"TTSWorker: 任务处理失败: {e}")
                self.put_data(character_name, speech, item['sprite'], '')
                self.tts_queue.task_done()


class UIWorker(QThread):
    # 发送给主UI线程的信号
    update_sprite_signal = pyqtSignal(np.ndarray, float)
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
                # 从音频路径队列中获取数据
                output_data = self.audio_path_queue.get()
                if output_data is None:
                    break

                character_name = output_data['character_name']
                sprite_id = output_data['sprite']
                speech = output_data['speech']
                audio_path = output_data.get('audio_path','')

                if character_name == "旁白":
                    formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px; color:#84C2D5;'><b>{character_name}</b>：{speech}</p>"
                    chat_history.append(formatted_speech)
                    self.update_dialog_signal.emit(formatted_speech)
                    time.sleep(len(speech)//8)
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

                        rate = getCharacterScale(character_name)
                        self.update_sprite_signal.emit(cv_image, rate)
                    else:
                        print(f"UIWorker: 无法加载图片: {image_path}")
                except Exception as e:
                    print(f"UIWorker: 加载图片时出错: {e}")

                # 更新对话框文本
                formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:{character_config.color};'>{character_name}</b>：{speech}</p>"
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

def save_chat_history(filename, history):
    """根据提供的文件名保存聊天记录到 JSON 文件。"""
    if not filename:
        print("没有提供历史文件名，跳过保存。")
        return
    history_dir = Path(CHAT_HISTORY_PATH)
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / filename
    try:
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
        print(f"聊天记录已保存到 {history_path}")
    except Exception as e:
        print(f"保存聊天记录失败: {e}")

def load_chat_history(filename):
    """根据提供的文件名加载聊天记录。"""
    if not filename:
        print("没有提供历史文件名，跳过加载。")
        return
        
    messages=[]
    history_path = Path(CHAT_HISTORY_PATH) / filename
    if history_path.exists():
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            print(f"聊天记录已从 {history_path} 加载。")
        except Exception as e:
            print(f"加载聊天记录失败: {e}")

    global chat_history
    chat_history.clear()
    try:
        for message in messages:
            if message["role"] == 'user':
                chat_history.append(f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message['content']}</p>")
            if message['role'] == 'assistant':
                dialog = json.loads(message['content'])['dialog']
                for item in dialog:
                    chat_history.append(f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>{item['character_name']}</b>: {item['speech']}</p>")

    except Exception as e:
        print("显示聊天历史失败", e)
        return messages
    return messages


def clear_chat_history(history_file, ui_queue, llm_manager):
    global chat_history
    chat_history.clear()
    history_file_path =Path(history_file)
    if history_file_path.exists():
        history_file_path.unlink()

    llm_manager.clear_messages()

    ui_queue.put({
        'character_name':'旁白',
        'speech':'消息记录已清空',
        'sprite':'-1',
    })

def main():
    load_api_config_from_file()
    parser = argparse.ArgumentParser(description='示例脚本')
    # 添加参数
    parser.add_argument('--template', '-t', type=str, help='用户模板名称', default='komaeda_sprite')
    parser.add_argument('--voice_mode', '-v', type=str, default='gen')
    parser.add_argument('--init_sprite_path', '-isp', type=str, default='')
    parser.add_argument('--history','--his',type=str, default='')
    parser.add_argument('--tts',type=str,default="gpt-sovits")
    parser.add_argument('--llm',type=str,default="deepseek")

    # 解析参数
    args = parser.parse_args()

    # 创建TTS管理器实例
    tts_manager = None
    if args.voice_mode == 'gen':
        adapter = TTSAdapterFactory.create_adapter(
            adapter_name=args.tts,
            gpt_sovits_work_path=api_config.get("gpt_sovits_api_path","") 
        )
        tts_manager = TTSManager(tts_server_url=api_config.get("gpt_sovits_url",""))
        tts_manager.set_tts_adapter(adapter=adapter)
    
    # 创建DeepSeek实例
    print("加载用户模板...", args)

    messages = []
    if args.history:
        messages = load_chat_history(args.history)

    user_template = ""
    with open(f'./data/character_templates/{args.template}.txt', 'r', encoding='utf-8') as f:
        user_template = f.read()

    llm_provider = api_config.get("llm_provider","Deepseek")
    llm_model = api_config.get("llm_model").get(llm_provider,'')
    api_key =api_config.get("llm_api_key").get(llm_provider,'')
    if not llm_provider:
        print("Please choose the llm provider")
        return
    llm_adapter = LLMAdapterFactory.create_adapter(llm_provider=llm_provider, api_key=api_key,base_url=api_config.get("llm_base_url",""), model = llm_model)
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

    init_sprite_path = args.init_sprite_path
    print (init_sprite_path)
    if not init_sprite_path:
        init_sprite_path = './data/sprite/usami/Danganronpa_V3_Monomi_Bonus_Mode_Sprites_14.webp'
        window.setDisplayWords("<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:#e6b2b2'>兔兔美</b>：欢迎来到新世界程序，希望你和大家能开启love love~的新学期，快和大家聊天吧</p>")

    # 更新初始立绘
    init_image = cv2.imread(init_sprite_path, cv2.IMREAD_UNCHANGED)
    if init_image is not None:
        if init_image.shape[2] == 3:
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGR2RGB)
            alpha_channel = np.full((init_image.shape[0], init_image.shape[1]), 255, dtype=np.uint8)
            init_image = cv2.merge([init_image, alpha_channel])
        elif init_image.shape[2] == 4:
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGRA2RGBA)
    window.update_image(init_image)
    window.setNotification("开始聊天吧……")

    # 连接 UI 信号到队列
    def on_message_submitted(message):
        user_input_queue.put(message)
        window.setNotification("您的消息已提交，正在等待LLM处理...")
    
    if messages:
        try:
            msg = ''
            if messages[-1]['role'] == 'assistant':
                msg = messages[-1]['content']
            elif len[messages] > 2:
                msg = messages[-2]['content']
            dialog = json.loads(msg)['dialog']
            audio_path_queue.put(dialog[-1])
        except Exception as e:
            print('更新初始立绘失败', e)

    
    window.message_submitted.connect(lambda message: on_message_submitted(message))
    window.open_chat_history_dialog.connect(lambda: window.open_history_dialog(getHistory()))
    window.change_voice_language.connect(lambda lang: tts_manager.set_language(lang) if tts_manager else None)
    window.close_window.connect(app.quit)
    window.clear_chat_history.connect(lambda: clear_chat_history(history_file=args.history, ui_queue=audio_path_queue, llm_manager=llm_manager))
    
    # 确保在程序退出时停止所有线程
    app.aboutToQuit.connect(llm_worker.quit)
    app.aboutToQuit.connect(tts_worker.quit)
    app.aboutToQuit.connect(ui_worker.quit)
    app.aboutToQuit.connect(lambda :save_chat_history(args.history,llm_manager.get_messages()))

    window.show()

    app.exec_()

if __name__ == "__main__":
    main()