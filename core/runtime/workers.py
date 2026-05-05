import re
import time
import traceback
from queue import Queue
from pathlib import Path
from typing import Optional

from i18n import tr

from PySide6.QtCore import QThread

# 假设以下依赖文件已在项目路径中
from llm.llm_manager import STREAM_REASONING_DELTA_KEY
from llm.tools.tool_manager import ToolManager
import threading
import pygame
import sys
current_script = Path(__file__).resolve()
project_root = current_script.parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入 ConfigManager 和 Pydantic 消息模型
from config.config_manager import ConfigManager
from core.messaging.message import UserInputMessage, LLMDialogMessage, TTSOutputMessage
from core.runtime.app_runtime import get_app_runtime, try_get_app_runtime, tts_emit_to_ui_queue
from core.messaging.stream_parser import LlmResponseStreamParser
from core.handlers.handler_registry import default_tts_handler_chain, default_ui_output_handler_chain
# --- 抽象 Worker 接口定义 ---

class BaseWorker(QThread):
    """
    Worker 抽象基类，定义了统一 QThread 基础。
    """

    def __init__(self, *args, **kwargs):
        # 确保 QThread 初始化
        QThread.__init__(self, *args, **kwargs)
        self.running = True

    def run(self):
        """Worker 线程的主执行逻辑"""
        pass

    def stop(self):
        """停止 Worker 线程的优雅方法"""
        self.running = False
        # QThread 的停止通常在主应用退出时由 app.aboutToQuit.connect(worker.quit) 处理

def getCharacter(name: str):
    rt = try_get_app_runtime()
    if rt is not None:
        return rt.config.get_character_by_name(name)
    return ConfigManager().get_character_by_name(name)


def _busy_preview_reasoning(raw: str, max_len: int = 200) -> str:
    """压成单行摘要供底栏显示（与 ui_message_handler 中 COT 预览一致）。"""
    s = re.sub(r"<[^>]+>", " ", raw or "")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


class LLMWorker(BaseWorker):
    def __init__(
        self,
        input_queue: Queue[UserInputMessage],
        output_queue: Queue[LLMDialogMessage],
        parent=None,
    ):
        super().__init__(parent)
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.llm_manager = rt.llm_manager
        self.user_input_queue = input_queue
        self.tts_queue = output_queue
        self.tool_manager = ToolManager()

    def run(self):
        while self.running:
            try:
                # 从用户输入队列中获取任务，阻塞等待
                # 期望获取的是 UserInputMessage 实例
                message: UserInputMessage = self.user_input_queue.get()
                if message is None:
                    break
                
                print(f"LLMWorker: 开始处理消息: {message.text}")
                self.ui_update_manager.post_notification("发送成功，正在等待回复中...")

                # 将用户消息添加到历史 (以 UI 格式和 LLM 格式分别处理)
                formatted_user_message = f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message.text}</p>"
                self.ui_update_manager.chat_history.append(formatted_user_message)
                
                start_time = time.perf_counter()
                
                # 统一获取响应流
                is_streaming = get_app_runtime().config.config.api_config.is_streaming
                raw_response = self.llm_manager.chat(message.text, stream=is_streaming)

                # 如果不是流式，将其包装成一个列表，使下文的 for 循环可以统一处理
                if is_streaming:
                    response_stream = raw_response
                else:
                    # 包装成可迭代对象，模拟流式的一个 chunk
                    response_stream = [raw_response]

                parser = LlmResponseStreamParser()
                reasoning_shown = ""

                for chunk in response_stream:
                    if isinstance(chunk, dict) and STREAM_REASONING_DELTA_KEY in chunk:
                        reasoning_shown += chunk[STREAM_REASONING_DELTA_KEY]
                        preview = _busy_preview_reasoning(reasoning_shown)
                        label = tr("desktop.thinking_busy_prefix")
                        bar_text = f"{label} · {preview}" if preview else label
                        self.ui_update_manager.post_busy_bar(bar_text, 0.0)
                        continue
                    chunk_message = (
                        chunk if isinstance(chunk, str) else str(chunk) if chunk is not None else ""
                    )
                    for llm_dialog in parser.feed(chunk_message):
                        self.tts_queue.put(llm_dialog)

                if reasoning_shown:
                    self.ui_update_manager.hide_busy_bar()
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
    def __init__(
        self,
        input_queue: Queue[LLMDialogMessage],
        output_queue: Queue[TTSOutputMessage],
        parent=None,
    ):
        super().__init__(parent)
        self.tts_queue = input_queue
        self.audio_path_queue = output_queue
        self.tts_message_dispatcher = default_tts_handler_chain()
        self.tts_message_dispatcher.init_handlers()

    def put_data(self, character_name: str, speech: str, sprite: str, audio_path, is_system_message: bool = False, effect: str = ""):
        """与 handler 中 tts_emit_to_ui_queue 一致，供本 worker 异常路径使用。"""
        tts_emit_to_ui_queue(
            character_name, speech, sprite, audio_path or "",
            is_system_message=is_system_message, effect=effect,
        )

    def run(self):
        while self.running:
            character_name = "未知"
            item: Optional[LLMDialogMessage] = None
            try:
                item = self.tts_queue.get()
                if item is None:
                    break
                character_name = item.character_name
                self.tts_message_dispatcher.dispatch(item)
            except Exception as e:
                print(f"TTSWorker: 任务处理失败: {e}")
                traceback.print_exc()
                if item is not None:
                    self.put_data(
                        get_app_runtime().opencc.convert(item.character_name),
                        item.speech,
                        str(item.sprite) if item.sprite is not None else "-1",
                        "",
                        is_system_message=False,
                        effect=item.effect,
                    )

    def quit(self):
        """确保在退出前能解锁队列"""
        self.running = False
        # 放置一个 None 到队列中，以防 worker 阻塞在 get() 上
        self.tts_queue.put(None)
        super().quit()

class UIWorker(QThread):
    def __init__(self, input_queue: Queue[TTSOutputMessage], parent=None):
        super().__init__(parent)
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.audio_path_queue = input_queue
        self.running = True
        self.task_done_requested = threading.Event() # 使用 Event 对象作为跳过标志
        self.current_audio_path = None
        self.DIALOG_CHANNEL_ID = 7
        self.ui_out_dispatcher = default_ui_output_handler_chain()

        self.init_channel()
        br = get_app_runtime().ui_playback
        br.task_done_requested = self.task_done_requested
        br.dialog_channel = self.dialog_channel
        self.ui_out_dispatcher.init_handlers()

    def init_channel(self):
        # --- 新增 Mixer 初始化和通道获取 ---
        try:
            pygame.mixer.init()
            # 确保有足够的通道，此处至少需要 DIALOG_CHANNEL_ID + 1 个
            if pygame.mixer.get_num_channels() < self.DIALOG_CHANNEL_ID + 1:
                pygame.mixer.set_num_channels(self.DIALOG_CHANNEL_ID + 1)
            
            # 获取对话专用通道
            self.dialog_channel: pygame.mixer.Channel = pygame.mixer.Channel(self.DIALOG_CHANNEL_ID)
            print(f"UIWorker: 对话播放通道初始化成功，使用通道 {self.DIALOG_CHANNEL_ID}")

        except Exception as e:
            print(f"UIWorker: Pygame Mixer 初始化或通道获取失败: {e}")
            self.dialog_channel = None # 如果失败，则禁用音频播放
        # --- 结束新增 ---

    def skip_speech(self):
        """跳过当前对话"""
        if self.audio_path_queue.empty():
            return
        if self.dialog_channel and self.dialog_channel.get_busy():
            self.dialog_channel.stop()

        self.current_audio_path = None
        get_app_runtime().ui_playback.current_audio_path = None

        self.task_done_requested.set()

    def run(self):
        while self.running:
            character_name = ""
            speech = ""
            try:
                self.task_done_requested.clear()
                output_data: TTSOutputMessage = self.audio_path_queue.get()
                if output_data is None:
                    break
                character_name = output_data.character_name
                speech = output_data.speech or ""
                self.ui_out_dispatcher.dispatch(output_data)
            except Exception as e:
                traceback.print_exc()
                print(f"UIWorker: 任务处理失败: {e}")
                try:
                    self.ui_update_manager.post_notification(f"界面更新失败: {e}")
                except Exception:
                    pass
                if not self.task_done_requested.is_set():
                    wait = max(len(speech) / 10, 0.3) if speech else 0.3
                    self.task_done_requested.wait(timeout=wait)
                self.audio_path_queue.task_done()