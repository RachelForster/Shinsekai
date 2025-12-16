import threading
import time
import numpy as np
from typing import Callable, Optional, List, Tuple
import collections
import io

# 假设已安装的依赖
try:
    from faster_whisper import WhisperModel
    import pyaudio
    # 实际应用中，您可能还需要一个 Voice Activity Detection (VAD) 库
    # 例如：webrtcvad 或 Silero VAD
    # from py_webrtcvad import Vad # 仅作示例
    WHISPER_AVAILABLE = True
except ImportError:
    print("WARNING: faster-whisper 或 pyaudio 未安装，ASRManager 将以模拟模式运行。请安装依赖：pip install faster-whisper pyaudio")
    WHISPER_AVAILABLE = False


class WhisperASRManager:
    """
    基于 faster-whisper 的实时语音识别 (ASR) 管理器。

    使用 PyAudio 捕获麦克风输入，使用 Whisper 进行转录，并实现静默超时逻辑。
    """
    
    # 麦克风配置
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000 # Whisper 要求的采样率
    CHUNK_SIZE = 1024 # 音频流块大小 (用于实时处理)
    
    # 静默检测配置 (这里的实现是简化的，实际项目中需要 VAD)
    SILENCE_THRESHOLD_SAMPLES = RATE * 5 # 5秒的静默样本数

    def __init__(self, model_size="small", device="gpu"):
        """初始化 Whisper 模型"""
        self.model_size = model_size
        self.device = device
        self._final_text = ""
        self.running = False
        
        if WHISPER_AVAILABLE:
            try:
                # 推荐使用 faster-whisper
                self.model = WhisperModel(model_size, device=device, compute_type="int8")
                print(f"WhisperASRManager: {model_size} 模型在 {device} 上加载成功。")
            except Exception as e:
                print(f"Whisper 模型加载失败: {e}")
                self.model = None
                self.WHISPER_AVAILABLE = False
        else:
            self.model = None


    def _transcribe_audio(self, audio_data: np.ndarray) -> str:
        """
        使用 Whisper 模型转录音频数据。
        
        Args:
            audio_data: 单声道 16kHz 采样的浮点型音频数据 (e.g., np.float32)。
        
        Returns:
            str: 识别到的文本。
        """
        if not self.model:
            return "Whisper 识别失败 (模拟文本)"

        # Whisper 模型需要的是 float32 类型的音频数据
        # 1. 对音频数据进行归一化到 [-1, 1] (如果不是 float 类型)
        # 2. 调用模型进行识别
        
        # faster-whisper 的 transcribe 方法接受的是 float 类型的 NumPy 数组
        # 假设输入的 audio_data 已经是适合 Whisper 的格式 (16kHz, float32)
        
        segments, info = self.model.transcribe(
            audio_data, 
            beam_size=5, 
            language="zh", # 指定语言以加速识别
            vad_filter=True # 利用 faster-whisper 内置的 VAD 过滤器
        )
        
        recognized_text = "".join(segment.text for segment in segments).strip()
        return recognized_text

    
    def listen_and_stream(self, 
                          callback: Callable[[str], None], 
                          silence_timeout: float = 5.0,
                          stop_event: Optional[threading.Event] = None) -> str:
        """
        持续监听并流式传输识别结果。

        Args:
            callback: 实时识别到文本块时调用的函数 (str -> None)。
            silence_timeout: 静默超时时间（秒）。如果在这个时间内没有检测到有效语音，则自动停止。
            stop_event: 一个 threading.Event，当被设置时，立即停止监听。

        Returns:
            str: 最终识别到的文本。
        """
        if not self.model and WHISPER_AVAILABLE:
            # 如果模型加载失败，但在依赖检查时可用，则不应运行
            return "ASR Manager 未正确初始化。"
        
        # 使用 PyAudio 设置音频流
        p = pyaudio.PyAudio()
        stream = p.open(format=self.FORMAT,
                        channels=self.CHANNELS,
                        rate=self.RATE,
                        input=True,
                        frames_per_buffer=self.CHUNK_SIZE)

        self.running = True
        self._final_text = ""
        # 实时处理需要一个缓冲区来存储音频，然后批量处理
        audio_buffer = bytearray()
        
        # 用于静默检测的缓冲区
        # 存储最近 N 秒的音频数据，用于判断是否有语音活动
        # 使用 deque 限制其最大长度 (例如：存储 6 秒的音频数据，用于检测 5 秒静默)
        max_buffer_bytes = int(self.RATE * 2 * (silence_timeout + 1)) # 采样率*2字节/采样*时间
        
        # 存储所有已收集但尚未转录的音频数据
        collected_speech_frames = collections.deque() 
        last_speech_time = time.time()
        
        # 最小处理的音频长度 (例如 2 秒)
        MIN_PROCESS_DURATION = 2.0
        MIN_PROCESS_FRAMES = int(self.RATE * MIN_PROCESS_DURATION)
        
        print(f"ASRManager: 开始监听 (静默超时: {silence_timeout}s)...")
        
        while self.running:
            try:
                # --- 1. 检查外部停止信号 ---
                if stop_event and stop_event.is_set():
                    print("ASRManager: 收到外部停止信号，停止监听。")
                    break

                # --- 2. 检查静默超时 ---
                if time.time() - last_speech_time >= silence_timeout:
                    print(f"ASRManager: 静默时间达到 {time.time() - last_speech_time:.2f}s，超过 {silence_timeout}s 超时限制，自动停止。")
                    break
                
                # --- 3. 读取音频块 ---
                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                # 将原始字节数据转换为 numpy 数组
                np_data = np.frombuffer(data, dtype=np.int16)
                
                # --- 4. 简化的 VAD/静默检测 ---
                # 实际应用中，这里需要一个 VAD 模型来判断是否是语音
                # 简化的方法：检查音量 (RMS) 是否超过阈值
                rms = np.sqrt(np.mean(np_data**2))
                IS_SPEECH = rms > 40 # 假设 RMS 阈值为 100 (需根据实际麦克风调整)

                if IS_SPEECH:
                    # 检测到语音，重置静默计时器
                    last_speech_time = time.time()
                    collected_speech_frames.append(np_data)

                    # 如果收集的语音达到最小处理长度，则进行转录
                    if len(collected_speech_frames) * self.CHUNK_SIZE >= MIN_PROCESS_FRAMES:
                        # 收集所有帧并清空缓冲区
                        all_speech_data = np.concatenate(list(collected_speech_frames))
                        collected_speech_frames.clear()
                        
                        # 转换为 Whisper 需要的 float32 格式并归一化
                        audio_float = all_speech_data.astype(np.float32) / 32768.0 
                        
                        # 进行转录
                        chunk_text = self._transcribe_audio(audio_float)
                        if chunk_text:
                            # 假设 Whisper 在流式模式下可以返回整个句子的转录
                            # 实际流式识别更复杂，这里只返回累积结果
                            self._final_text += chunk_text + " "
                            callback(self._final_text.strip())
                            print(f"ASRManager: 实时识别: {self._final_text.strip()}")
                
                else:
                    # 识别到静默，继续检查静默超时
                    pass

            except Exception as e:
                print(f"ASRManager: 监听过程中发生错误: {e}")
                self.running = False
                break
                
        # --- 循环结束，清理资源和处理最后剩余的音频 ---
        stream.stop_stream()
        stream.close()
        p.terminate()

        # 处理最后一次静默或停止时缓冲区中剩余的音频
        if collected_speech_frames:
            print("ASRManager: 处理最后剩余的音频...")
            all_speech_data = np.concatenate(list(collected_speech_frames))
            audio_float = all_speech_data.astype(np.float32) / 32768.0
            last_text = self._transcribe_audio(audio_float)
            self._final_text += last_text + " "
            
        final_result = self._final_text.strip()
        print(f"ASRManager: 监听结束。最终文本: '{final_result}'")
        
        return final_result