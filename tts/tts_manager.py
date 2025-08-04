# tts.py (TTS模块)
import os
import re
import requests
import threading
import queue
import wave
from datetime import datetime
import subprocess
import json
import uuid

#  GPT-SoVITS TTS管理器
class TTSManager:
    def __init__(self, character_ui_url="http://localhost:7888/alive", tts_server_url="http://127.0.0.1:9880/tts"):
        self.audio_cache_dir = r".\cache\audio"
        self.character_ui_url = character_ui_url
        self.tts_server_url = tts_server_url

        # 工作队列，处理说话，唱歌请求
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
        
        # TTS配置, TODO: 这些配置可以从配置文件中读取
        self.ref_audio_path = r"C:\AI\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50\output\slicer_opt\komaeda01.mp3_0000204800_0000416320.wav",
        self.ref_text = "だからって放置するわけにもいかないよね。あのゲームは今回の動機なんだからさ。"
        self.ref_lang = "ja"

    def _process_queue(self):
        """工作线程，串行处理队列中的任务"""
        while True:
            task = self.task_queue.get()
            if task is None:  # 终止信号
                break
            try:
                if task['type'] == 'speak':
                    self._send_audio_to_character(task['file_path'])
                elif task['type'] == 'sing':
                    self._send_song_to_character(task['voice_path'], task['music_path'])
            except Exception as e:
                print(f"TTS任务执行失败: {e}")
            finally:
                self.task_queue.task_done()

    """
    生成TTS语音
    参数:
        text: 要转换为语音的文本
        text_processor: 文本处理器，用于预处理文本
        voice_language: 语音语言，默认为日语
    """
    def generate_tts(self, text, text_processor=None, voice_language='ja'):
        """生成TTS语音"""
        # 预处理文本
        if text_processor:
            text = text_processor.remove_parentheses(text)
            text = text_processor.html_to_plain_qt(text)
            language = text_processor.decide_language(text)
            text = text_processor.replace_names(text)
            text = text_processor.libre_translate(text, source=language, target= voice_language)
            text = text_processor.replace_watashi(text)

        params = {
            "ref_audio_path": r"C:\AI\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50\output\slicer_opt\komaeda01.mp3_0000204800_0000416320.wav",
            "prompt_text": self.ref_text,
            "prompt_lang": self.ref_lang,
            "text": text,
            "text_lang": voice_language,
            "text_split_method": "cut5",
            "batch_size": 1,
        }

        print("请求参数:", params)
        
        try:
            response = requests.post(self.tts_server_url, json=params)
            file_path = 'temp.wav'
            with open(file_path, 'wb') as f:
                f.write(response.content)

            # 保存临时音频文件
            file_path = os.path.abspath(file_path)
            print("音频文件保存路径:", file_path)
            return file_path
        except Exception as e:
            print("TTS生成失败:", e)
            return None

    def queue_speech(self, text, language_processor=None):
        """将文本加入TTS队列"""
        file_path = self.generate_tts(text, language_processor)
        if file_path:
            self.task_queue.put({
                'type': 'speak',
                'file_path': file_path
            })
    
    def queue_song(self, voice_path, music_path):
        """将歌曲加入队列"""
        self.task_queue.put({
            'type': 'sing',
            'voice_path': voice_path,
            'music_path': music_path
        })
    
    def _send_audio_to_character(self, file_path):
        """发送音频文件到角色UI"""
        params = {
            "type": "speak",
            "speech_path": file_path,
        }
        try:
            response = requests.post(self.character_ui_url, json=params)
            if response.status_code == 200:
                print("音频发送成功:", file_path)
            else:
                print("音频发送失败:", response.text)
        except Exception as e:
            print("发送音频到角色UI失败:", e)
    
    def _send_song_to_character(self, voice_path, music_path):
        """发送歌曲到角色UI"""
        params = {
            "type": "sing",
            "voice_path": voice_path,
            "music_path": music_path,
        }
        try:
            response = requests.post(self.character_ui_url, json=params)
            if response.status_code == 200:
                print("歌曲发送成功:", voice_path, music_path)
            else:
                print("歌曲发送失败:", response.text)
        except Exception as e:
            print("发送歌曲到角色UI失败:", e)

    # TODO: 实现加载TTS模型的逻辑, 整合GPT-SoVITS server
    def load_tts_model(self):
        """加载TTS模型"""
        os_path = r"C:\AI\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50"
        embeded_python_path = r"C:\AI\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50\runtime\python.exe"
        path = r"C:\AI\GPT-SoVITS\GPT-SoVITS-v2pro-20250604-nvidia50\api_v2.py"
        # 工作环境为gpt-sovits目录
        subprocess.Popen([embeded_python_path, path], cwd=os_path)

    def shutdown(self):
        """关闭队列和工作线程"""
        self.task_queue.put(None)
        self.worker_thread.join()