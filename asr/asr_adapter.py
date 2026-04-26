from abc import ABC, abstractmethod
import json
import os
import sys
import threading
from typing import Callable, Optional
from pathlib import Path

# 定义转录回调函数的类型签名
TranscriptionCallback = Callable[[str, bool], None]

class ASRAdapter(ABC):
    """
    抽象的 ASR 适配器接口 (Target)。
    定义了所有实时语音转文字服务必须提供的标准方法。
    """
    
    def __init__(self, language: str, callback: TranscriptionCallback):
        """
        初始化适配器。
        
        Args:
            language (str): 识别语言。
            callback (TranscriptionCallback): 用于处理实时转录结果的回调函数。
        """
        self.language = language
        self.callback = callback
    
    @abstractmethod
    def start(self):
        """
        启动实时录音和转录服务。
        """
        pass

    @abstractmethod
    def stop(self):
        """
        停止实时录音和转录服务。
        """
        pass

    @abstractmethod
    def get_status(self) -> str:
        """
        获取服务的当前状态（例如：'Running', 'Stopped', 'Error'）。
        """
        pass
    
    @abstractmethod
    def pause(self):
        """暂停识别。"""
        pass

    @abstractmethod
    def resume(self):
        """恢复识别。"""
        pass

class RealtimeSTTAdapter(ASRAdapter):
    """
    RealtimeSTT 库的适配器。
    将 RealtimeSTT 的 AudioToTextRecorder 行为映射到 ASRAdapter 接口。
    """

    def __init__(self, language: str, callback: TranscriptionCallback, model_name: str = "small"):
        super().__init__(language, callback)
        # 自动定位你的虚拟环境中的 nvidia 库路径
        venv_path = sys.prefix
        nvidia_base = os.path.join(venv_path, r'Lib\site-packages\nvidia')

        # 需要加入搜索路径的子目录
        sub_dirs = [
            r'cudnn\bin',
            r'cublas\bin',
            r'curand\bin'
        ]

        for sub in sub_dirs:
            full_path = os.path.join(nvidia_base, sub)
            if os.path.exists(full_path):
                os.add_dll_directory(full_path)
                print(f"已添加 DLL 搜索路径: {full_path}")


        from RealtimeSTT import AudioToTextRecorder

        self._recorder: Optional[AudioToTextRecorder] = None
        self._is_running = False
        self.model_name = model_name

    def _setup_recorder(self):
        """配置和创建 RealtimeSTT 录音器实例。"""
        print(f"RealtimeSTT: 正在配置模型 {self.model_name}...")
        
        # 将 RealtimeSTT 的回调函数包装起来，以便传递给外部的 self.callback
        def internal_callback(text, is_partial):
            self.callback(text, is_partial)
        
        from RealtimeSTT import AudioToTextRecorder
        self._recorder = AudioToTextRecorder(
            model=self.model_name,
            language=self.language,
            compute_type="float16",  # 可选参数，根据需要调整
            device="cuda",  # 可选参数，根据需要调整
            initial_prompt="这是一段中文语音：",
            on_realtime_transcription_update=internal_callback
        )

    def start(self):
        """启动 RealtimeSTT 录音和转录。"""
        if self._is_running:
            print("RealtimeSTT: 已在运行。")
            return
            
        if self._recorder is None:
            self._setup_recorder()
            
        print("RealtimeSTT: 启动录音...")
        self._recorder.start_recording()
        self._is_running = True
        print("RealtimeSTT: 启动完成。")

    def stop(self):
        """停止 RealtimeSTT 录音和转录。"""
        if not self._is_running or self._recorder is None:
            print("RealtimeSTT: 未在运行。")
            return

        print("RealtimeSTT: 正在停止...")
        self._recorder.stop_recording()
        self._is_running = False
        print("RealtimeSTT: 停止完成。")

    def get_status(self) -> str:
        """获取 RealtimeSTT 的运行状态。"""
        return "Running" if self._is_running else "Stopped"

    def pause(self):
        if self._is_running and self._recorder:
            print("RealtimeSTT: 暂停录制...")
            self._recorder.stop_recording() # 停止录制但保留模型加载
            self._is_running = False

    def resume(self):
        if not self._is_running and self._recorder:
            print("RealtimeSTT: 恢复录制...")
            self._recorder.start_recording()
            self._is_running = True

# Vosk 模型的路径（请根据实际下载的模型路径修改）
VOSK_MODEL_PATH = "./assets/system/models/vosk-model-small-cn-0.22"

class VoskAdapter(ASRAdapter):
    """
    Vosk 库的适配器。
    将 Vosk 的流式处理逻辑映射到 ASRAdapter 接口。
    """
    def __init__(self, language: str, callback: TranscriptionCallback, model_path: str = VOSK_MODEL_PATH):
        # 禁止在模块顶层 import vosk：会立刻执行其 open_dll/add_dll_directory，冻结时路径常无效。
        import pyaudio
        from vosk import Model, KaldiRecognizer  # noqa: E402

        self._pyaudio = pyaudio
        self._KaldiRecognizer = KaldiRecognizer
        super().__init__(language, callback)
        self.model_path = Path(model_path).absolute().as_posix()
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        # 暂停事件
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始状态为“不暂停”
        
        # 音频配置
        self.samplerate = 16000
        self.chunk_size = 8192

        

        try:
            self.model = Model(model_path=self.model_path)
        except Exception as e:
            print(f"Error loading Vosk model from {self.model_path}: {e}")
            self.model = None

    def _vosk_recognition_loop(self):
        """在独立线程中运行的 Vosk 识别循环。"""
        if self.model is None:
            return
        pyaudio = self._pyaudio
        KaldiRecognizer = self._KaldiRecognizer

        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=self.samplerate,
                        input=True,
                        frames_per_buffer=self.chunk_size)

        recognizer = KaldiRecognizer(self.model, self.samplerate)
        stream.start_stream()
        
        while self._is_running:
            if not self._pause_event.is_set():
                # 如果处于暂停状态，休眠一小会，避免占用 CPU
                import time
                time.sleep(0.1)
                continue

            data = stream.read(self.chunk_size, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                # 最终结果 (Final Result)
                result_json = json.loads(recognizer.Result())
                if result_json.get('text'):
                    self.callback(result_json['text'], is_partial=False)
            else:
                # 部分结果 (Partial Result)
                result_json = json.loads(recognizer.PartialResult())
                if result_json.get('partial'):
                    self.callback(result_json['partial'], is_partial=True)

        stream.stop_stream()
        stream.close()
        p.terminate()
        print("Vosk: 识别循环结束。")

    def start(self):
        """启动 Vosk 识别线程。"""
        if self._is_running:
            print("Vosk: 适配器已在运行。")
            return
        
        if self.model is None:
            print("Vosk: 无法启动识别，因为模型加载失败。")
            return

        print("Vosk: 启动识别...")
        self._is_running = True
        import threading # 仅在需要时导入
        self._thread = threading.Thread(target=self._vosk_recognition_loop)
        self._thread.start()
        print("Vosk: 启动完成。")

    def stop(self):
        """停止 Vosk 识别线程。"""
        if not self._is_running:
            return

        print("Vosk: 正在停止...")
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join() # 等待线程安全退出
        print("Vosk: 停止完成。")

    def get_status(self) -> str:
        """获取 Vosk 的运行状态。"""
        return "Running" if self._is_running else "Stopped"
    
    def pause(self):
        """暂停 Vosk 识别。"""
        if self._is_running:
            print("Vosk: 暂停识别...")
            self._pause_event.clear()  # 设置为暂停状态
    
    def resume(self):
        """恢复 Vosk 识别。"""
        if self._is_running:
            print("Vosk: 恢复识别...")
            self._pause_event.set()  # 设置为运行状态