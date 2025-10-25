import abc
from abc import ABC, abstractmethod
import json
import time
import traceback
from queue import Queue
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt5.QtCore import QThread, pyqtSignal, QObject

# 假设以下依赖文件已在项目路径中
from llm.llm_manager import LLMManager # 假设的依赖
from llm.text_processor import TextProcessor # 假设的依赖
from tts.tts_manager import TTSManager # 假设的依赖
from opencc import OpenCC # 假设的依赖
import yaml
import numpy as np
import threading
import cv2
import pygame
import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入 ConfigManager 和 Pydantic 消息模型
from config.config_manager import ConfigManager # ConfigManager 是单例
from core.message import UserInputMessage, LLMDialogMessage, TTSOutputMessage

# --- 抽象 Worker 接口定义 ---

class BaseWorker(QThread):
    """
    Worker 抽象基类，定义了统一 QThread 基础。
    """
    # 统一的信号，用于通知主线程（UI）状态更新
    notification_signal = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        # 确保 QThread 初始化
        QThread.__init__(self, *args, **kwargs)
        self.running = True
        # 在 Worker 内部获取 ConfigManager 单例，以便读取配置
        self.config_manager = ConfigManager()

    def run(self):
        """Worker 线程的主执行逻辑"""
        pass

    def stop(self):
        """停止 Worker 线程的优雅方法"""
        self.running = False
        # QThread 的停止通常在主应用退出时由 app.aboutToQuit.connect(worker.quit) 处理

def getCharacter(name: str):
    return ConfigManager().get_character_by_name(name)

class LLMWorker(BaseWorker):
    # 发送通知给主UI线程的信号，与 BaseWorker 的 notification_signal 相同
    update_notification_signal = BaseWorker.notification_signal 

    def __init__(self, llm_manager: LLMManager, user_input_queue: Queue, tts_queue: Queue, parent=None, chat_history=None):
        super().__init__(parent)
        self.llm_manager = llm_manager
        # 队列中传入和传出的应是 Pydantic 消息模型
        self.user_input_queue: Queue[UserInputMessage] = user_input_queue
        self.tts_queue: Queue[LLMDialogMessage] = tts_queue
        self.chat_history = chat_history

    def run(self):
        while self.running:
            try:
                # 从用户输入队列中获取任务，阻塞等待
                # 期望获取的是 UserInputMessage 实例
                message: UserInputMessage = self.user_input_queue.get()
                if message is None:
                    break
                
                print(f"LLMWorker: 开始处理消息: {message.text}")
                self.update_notification_signal.emit("发送成功，正在等待回复中...")

                # 将用户消息添加到历史 (以 UI 格式和 LLM 格式分别处理)
                formatted_user_message = f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message.text}</p>"
                self.chat_history.append(formatted_user_message)
                
                start_time = time.perf_counter()
                
                # chat 函数的输入是原始文本
                response_stream = self.llm_manager.chat(message.text, stream=True)
                
                response_buffer = ""
                content = "" # 记录 LLM 的完整回复内容
                
                start_index = 0
                for chunk in response_stream:
                    # 检查是否为完整消息块
                    chunk_message = chunk.choices[0].delta.content
                    if chunk_message:
                        response_buffer += chunk_message
                        content += chunk_message

                    while '}' in response_buffer:
                        end_index = response_buffer.find('}') + 1
                        start_index_temp = end_index -1
                        while start_index_temp >=0:
                            if response_buffer[start_index_temp] == '{':
                                break
                            start_index_temp -= 1
                        if start_index_temp < 0:
                            break
                        
                        try:
                            # 确保 JSON 结构完整
                            json_str = response_buffer[start_index_temp:end_index]
                            print(json_str)

                            dialog_item = json.loads(json_str)
                            # 使用 Pydantic 模型验证和封装数据
                            llm_dialog = LLMDialogMessage(**dialog_item)
                            
                            # 将 Pydantic 实例放入 tts_queue
                            self.tts_queue.put(llm_dialog)
                            response_buffer = response_buffer[end_index:].strip()

                        except json.JSONDecodeError as e:
                            # 如果解析失败，可能是JSON格式不完整，继续等待更多数据
                            print(f"JSON解析错误，继续等待：{e}")
                            traceback.print_exc()
                            break
                        except Exception as e:
                            print(f"Pydantic 验证或放入队列失败: {e}")
                            traceback.print_exc()
                            # 假设 JSON 结构正确但 Pydantic 验证失败，也跳出内层循环
                            response_buffer = response_buffer[end_index:].strip()
                            break

                # LLM 历史应记录完整的 JSON 字符串
                self.llm_manager.add_message("assistant",content)           
                end_time = time.perf_counter()                
                self.user_input_queue.task_done()

            except Exception as e:
                print(f"LLMWorker: 任务处理失败: {e}")
                traceback.print_exc()
                self.user_input_queue.task_done()
                
    def quit(self):
        """确保在退出前能解锁队列"""
        self.running = False
        # 放置一个 None 到队列中，以防 worker 阻塞在 get() 上
        self.user_input_queue.put(None)
        super().quit()


class TTSWorker(BaseWorker):
    def __init__(self, tts_manager: TTSManager, tts_queue: Queue, audio_path_queue: Queue, parent=None):
        super().__init__(parent)
        self.tts_manager = tts_manager
        # 队列中传入和传出的应是 Pydantic 消息模型
        self.tts_queue: Queue[LLMDialogMessage] = tts_queue
        self.audio_path_queue: Queue[TTSOutputMessage] = audio_path_queue
        self.text_processor = TextProcessor()
        self.cc = OpenCC('t2s')  # 繁体到简体转换器

    def put_data(self, character_name: str, speech: str, sprite: str, audio_path, is_system_message: bool = False):
        """将处理结果封装成 Pydantic 模型并放入下一个队列"""
        audio_path = audio_path or ""
        output_data = TTSOutputMessage(
            audio_path=audio_path,
            character_name=character_name,
            sprite=sprite,
            speech=speech,
            is_system_message=is_system_message
        )
        self.audio_path_queue.put(output_data)
        self.tts_queue.task_done()

    def run(self):
        while self.running:
            # 默认值，以防 try 块中出错导致未定义
            character_name = "未知"
            speech = "未知"
            
            try:
                # 期望获取的是 LLMDialogMessage 实例
                item: LLMDialogMessage = self.tts_queue.get()
                print("TTS Worker get an item")
                if item is None:
                    break

                character_name = item.character_name
                speech = item.speech
                sprite = item.sprite
                translate = item.translate
                
                # 繁简转换角色名
                character_name_s = self.cc.convert(character_name)

                # 检查是否为特殊系统消息
                if character_name_s in ["选项","数值","旁白"]:
                    # 对于选项、数值或通用旁白，直接放入下一队列
                    self.put_data(character_name_s, speech, '-1', '', is_system_message=True)
                    continue
                
                # 获取角色配置
                self.character_config = getCharacter(character_name_s)
                if self.character_config is None: 
                    raise ValueError(f"未找到角色配置: {character_name_s}")
                   
                # 准备生成语音
                speech_text = speech
                text_processor = self.text_processor

                if translate:
                    text_processor = None  # 如果有翻译则不使用文本处理
                    speech_text = translate

                audio_path = ''
                if self.tts_manager:
                    # 路径处理
                    model_info ={
                        'sovits_model_path': Path(self.character_config.sovits_model_path).resolve().as_posix(), 
                        'gpt_model_path': Path(self.character_config.gpt_model_path).resolve().as_posix(),
                    }
                    self.tts_manager.switch_model(model_info)

                    # 确保 sprite_id 是整数，且在合法范围内
                    try:
                        sprite_id = int(sprite) - 1
                        if sprite_id < 0 or sprite_id >= len(self.character_config.sprites):
                            raise IndexError("Sprite ID out of range")
                    except (ValueError, IndexError):
                        print(f"无效或缺失的立绘编号: {sprite}. 使用默认立绘。")
                        sprite_id = -1 # 默认使用第一个立绘的语音参考

                    # 语音参考处理
                    ref_audio_path = Path(self.character_config.refer_audio_path).resolve().as_posix()
                    prompt_text = self.character_config.prompt_text
                    
                    try:
                        sprite_data = self.character_config.sprites[sprite_id]
                        if sprite_data.get("voice_text", None):
                            # 如果特定立绘有自己的语音参考
                            ref_audio_path = Path(sprite_data.get("voice_path")).resolve().as_posix()
                            prompt_text = sprite_data.get("voice_text")
                    except Exception as e:
                        print("没有立绘")
                        
                    # 生成 TTS
                    audio_path = self.tts_manager.generate_tts(
                        speech_text, 
                        text_processor=text_processor,
                        ref_audio_path=ref_audio_path,
                        prompt_text=prompt_text,
                        prompt_lang=self.character_config.prompt_lang,
                        character_name=character_name_s,
                    )
                else:
                    # 如果没有 TTS Manager，尝试使用配置中的预设音频
                    audio_path = self.character_config.sprites[int(sprite) - 1].get('voice_path', '')
                    
                # 将包含音频路径和原始数据的字典放入音频路径队列
                self.put_data(character_name_s, speech, sprite, audio_path)
                print(f'TTSWorker put: {audio_path} into the UI queue')

            except Exception as e:
                print(f"TTSWorker: 任务处理失败: {e}")
                traceback.print_exc()
                # 失败时也必须调用 task_done，并通知 UI 这是一个非语音的旁白
                self.put_data(character_name_s, speech, '-1', '') # 使用 -1 表示无立绘或语音

    def quit(self):
        """确保在退出前能解锁队列"""
        self.running = False
        # 放置一个 None 到队列中，以防 worker 阻塞在 get() 上
        self.tts_queue.put(None)
        super().quit()

class UIWorker(QThread):
    # 发送给主UI线程的信号
    update_sprite_signal = pyqtSignal(np.ndarray, float)
    update_dialog_signal = pyqtSignal(str)
    update_notification_signal = pyqtSignal(str)
    update_option_signal = pyqtSignal(list)
    update_value_signal = pyqtSignal(str)
    
    def __init__(self, audio_path_queue: Queue, parent=None, chat_history=None):
        super().__init__(parent)
        self.audio_path_queue = audio_path_queue
        self.running = True
        self.task_done_requested = threading.Event() # 使用 Event 对象作为跳过标志
        self.current_audio_path = None
        self.chat_history = chat_history

    def skip_speech(self):
        """跳过当前对话"""
        if self.audio_path_queue.empty():
            return
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        
        # 尝试卸载音频，以防 run 循环还未执行到 unload
        if self.current_audio_path:
            try:
                pygame.mixer.music.unload() 
                self.current_audio_path = None
            except Exception as e:
                # 忽略卸载失败的错误，因为可能已经被 unload
                pass 
        self.task_done_requested.set()
    def _update_dialog(self, name: str, speech: str, color: str, is_system = True):
        if is_system:
            formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px; color:{color};'><b>{name}</b>：{speech}</p>"
        else:
            formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color:{color};'>{name}</b>：{speech}</p>"
        self.chat_history.append(formatted_speech)
        self.update_dialog_signal.emit(formatted_speech)
    def run(self):
        while self.running:
            try:
                self.task_done_requested.clear()
                # 从音频路径队列中获取数据
                output_data: TTSOutputMessage = self.audio_path_queue.get() 
                if output_data is None:
                    break
                
                # 解包 Pydantic 实例属性
                character_name = output_data.character_name
                sprite_id = output_data.sprite
                speech = output_data.speech
                audio_path = output_data.audio_path
                is_system_message = output_data.is_system_message
                
                if audio_path:
                    audio_path = Path(audio_path).as_posix()

                if is_system_message:
                    if character_name == "选项":
                        optionList = speech.split('/')
                        self.update_option_signal.emit(optionList)
                    elif character_name == "数值":
                        self.update_value_signal.emit(speech)
                    else:
                        self._update_dialog(character_name, speech, "#84C2D5")
                        if not self.task_done_requested.is_set():
                            self.task_done_requested.wait(timeout=max(len(speech)/10, 0.5))
                    continue

                # 获取角色配置
                character_config = getCharacter(character_name)
                
                if not character_config:
                    raise ValueError(f"未找到角色配置: {character_name}")

                # 更新 UI 通知
                self.update_notification_signal.emit(f"{character_name}正在回复……")
                
                # 更新对话框文本
                if speech:
                    self._update_dialog(character_name, speech, character_config.color, is_system=False)

                try:
                    # 更新立绘
                    image_path = character_config.sprites[int(sprite_id) - 1]['path']
                    image_path = Path(image_path).as_posix()
                    cv_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
                    if cv_image is not None:
                        if cv_image.shape[2] == 3:
                            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
                            alpha_channel = np.full((cv_image.shape[0], cv_image.shape[1]), 255, dtype=np.uint8)
                            cv_image = cv2.merge([cv_image, alpha_channel])
                        elif cv_image.shape[2] == 4:
                            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)

                        rate = character_config.sprite_scale
                        self.update_sprite_signal.emit(cv_image, rate)
                    else:
                        print(f"UIWorker: 无法加载图片: {image_path}")
                except Exception as e:
                    traceback.print_exc()
                    print(f"UIWorker: 加载图片时出错: {e}")


                min_stop_time = len(speech)//8
                start_time = time.perf_counter()
                # 播放音频
                audio_played = False
                self.current_audio_path = audio_path
                if audio_path and audio_path is not None and Path(audio_path).exists():
                    try:
                        pygame.mixer.init()
                        pygame.mixer.music.load(audio_path)
                        self.current_audio_path = audio_path
                        pygame.mixer.music.play()
                        audio_played = True
                        while pygame.mixer.music.get_busy() and not self.task_done_requested.is_set(): # 检查是否被请求跳过
                            time.sleep(0.1)

                    except Exception as e:
                        print(f"UIWorker: 播放音频时出错: {e}")

                    finally:
                        # 无论如何，尝试在 finally 中卸载资源
                        if audio_played:
                            try:
                                pygame.mixer.music.unload() 
                            except Exception:
                                pass # 忽略卸载失败
                        self.current_audio_path = None # 清除记录

                end_time = time.perf_counter()
                if not self.task_done_requested.is_set():
                    # 如果没有被跳过，则执行最小时间等待
                    remaining_time = min_stop_time - (end_time - start_time)
                    if remaining_time > 0:
                        # 使用 self.task_done_requested.wait() 代替 time.sleep()
                        # 这样如果 skip_speech() 在等待期间被调用，等待会立即停止。
                        self.task_done_requested.wait(timeout=remaining_time) 
            except Exception as e:
                traceback.print_exc()
                print(f"UIWorker: 任务处理失败: {e}")
                self._update_dialog(character_name, speech, "#84C2D5", character_name in [])
                if not self.task_done_requested.is_set():
                    self.task_done_requested.wait(timeout=len(speech)/10)
                self.audio_path_queue.task_done()