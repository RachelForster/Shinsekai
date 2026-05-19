import re
import traceback
from pathlib import Path
from typing import Optional

from i18n import tr
from sdk.logging.timing import tracker

from queue import Queue

from PySide6.QtCore import QThread

from sdk.graph import DagNode, Port

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
from sdk.messages import UserInputMessage, LLMDialogMessage, TTSOutputMessage
from core.runtime.app_runtime import get_app_runtime, try_get_app_runtime, tts_emit_to_ui_queue
from core.messaging.stream_parser import LlmResponseStreamParser
from core.handlers.handler_registry import default_tts_handler_chain, default_ui_output_handler_chain

# --- QThread + DagNode 基类 ---

class QThreadDagNode(DagNode, QThread):
    """每个 DagNode 自带一个 QThread 运行循环。"""

    def __init__(self, name: str, parent=None) -> None:
        DagNode.__init__(self, name)
        QThread.__init__(self, parent)
        self.running = True

    def start(self) -> None:
        if self.isRunning():
            return
        self.running = True
        QThread.start(self)

    def stop(self) -> None:
        """停止线程并等待退出（最多 3 秒）。"""
        self.running = False
        if not self.wait(3000):
            print(f"警告: {type(self).__name__} 线程未在 3 秒内退出，请检查阻塞中的外部调用")

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


class LLMWorker(QThreadDagNode):
    PORT_USER_INPUT = "user_input"
    PORT_LLM_OUTPUT = "llm_output"

    def __init__(
        self,
        input_queue: Queue[UserInputMessage] | None = None,
        output_queue: Queue[LLMDialogMessage] | None = None,
        parent=None,
        *,
        name: str = "llm_worker",
    ):
        super().__init__(name, parent=parent)
        self._app_inited = False
        self.user_input_queue = input_queue
        self.tts_queue = output_queue
        if input_queue is not None:
            self.bind_input(self.PORT_USER_INPUT, input_queue)
        if output_queue is not None:
            self.bind_output(self.PORT_LLM_OUTPUT, output_queue)

    def _init_app(self):
        if self._app_inited:
            return
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.llm_manager = rt.llm_manager
        self.user_input_queue = self.inq(self.PORT_USER_INPUT)
        self.tts_queue = self.outq(self.PORT_LLM_OUTPUT)
        self.tool_manager = ToolManager()
        self._app_inited = True

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_USER_INPUT: Port(self.PORT_USER_INPUT)}

    def outputs(self) -> dict[str, Port]:
        return {self.PORT_LLM_OUTPUT: Port(self.PORT_LLM_OUTPUT)}

    def run(self):
        self._init_app()
        while self.running:
            try:
                message: UserInputMessage = self.user_input_queue.get()
                if message is None:
                    break

                print(f"LLMWorker: 开始处理消息: {message.text}")
                tracker.start_cross("e2e")
                self.ui_update_manager.post_notification("发送成功，正在等待回复中...")

                formatted_user_message = f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message.text}</p>"
                self.ui_update_manager.chat_history.append(formatted_user_message)

                is_streaming = get_app_runtime().config.config.api_config.is_streaming
                with tracker.track("LLM chat total"):
                    raw_response = self.llm_manager.chat(message.text, stream=is_streaming)

                if is_streaming:
                    response_stream = raw_response
                else:
                    response_stream = [raw_response]

                parser = LlmResponseStreamParser()
                reasoning_shown = ""
                message_count = 0

                with tracker.track("LLM stream parse"):
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
                            message_count += 1
                            self.tts_queue.put(llm_dialog)

                if message_count == 0:
                    _msg = tr("desktop.llm_parse_empty")
                    if parser.has_errors:
                        _msg += "\n" + parser.last_error
                    elif parser.unparsed_remainder:
                        _msg += "\n" + tr("desktop.llm_parse_remainder", text=parser.unparsed_remainder)
                    self.ui_update_manager.post_busy_bar(_msg, 0.0)
                    from sdk.messages import TTSOutputMessage
                    get_app_runtime().audio_path_queue.put(TTSOutputMessage(
                        audio_path="", name="system", asset_id="-1",
                        text=_msg, is_system_message=True, effect="",
                    ))
                elif parser.has_errors:
                    _warn = tr("desktop.llm_parse_partial", n=parser.parse_failures)
                    print(f"LLMWorker: {_warn}")

                self.user_input_queue.task_done()

            except Exception as e:
                print(f"LLMWorker: 任务处理失败: {e}")
                traceback.print_exc()
                try:
                    from sdk.messages import TTSOutputMessage
                    _err = tr("desktop.llm_parse_empty") + f"\n{e}"
                    get_app_runtime().audio_path_queue.put(TTSOutputMessage(
                        audio_path="", name="system", asset_id="-1",
                        text=_err, is_system_message=True, effect="",
                    ))
                except Exception:
                    pass
                self.user_input_queue.task_done()

    def stop(self):
        self.running = False
        self.user_input_queue.put(None)
        super().stop()


class TTSWorker(QThreadDagNode):
    PORT_LLM_OUTPUT = "llm_output"
    PORT_TTS_OUTPUT = "tts_output"

    def __init__(
        self,
        input_queue: Queue[LLMDialogMessage] | None = None,
        output_queue: Queue[TTSOutputMessage] | None = None,
        parent=None,
        *,
        name: str = "tts_worker",
    ):
        super().__init__(name, parent=parent)
        self._app_inited = False
        self.tts_queue = input_queue
        self.audio_path_queue = output_queue
        self.tts_message_dispatcher = None
        if input_queue is not None:
            self.bind_input(self.PORT_LLM_OUTPUT, input_queue)
        if output_queue is not None:
            self.bind_output(self.PORT_TTS_OUTPUT, output_queue)

    def _init_app(self):
        if self._app_inited:
            return
        self.tts_queue = self.inq(self.PORT_LLM_OUTPUT)
        self.audio_path_queue = self.outq(self.PORT_TTS_OUTPUT)
        self.tts_message_dispatcher = default_tts_handler_chain()
        self.tts_message_dispatcher.init_handlers()
        self._app_inited = True

    def put_data(self, character_name: str, speech: str, sprite: str, audio_path, is_system_message: bool = False, effect: str = ""):
        """与 handler 中 tts_emit_to_ui_queue 一致，供本 worker 异常路径使用。"""
        tts_emit_to_ui_queue(
            character_name, speech, sprite, audio_path or "",
            is_system_message=is_system_message, effect=effect,
        )

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_LLM_OUTPUT: Port(self.PORT_LLM_OUTPUT)}

    def outputs(self) -> dict[str, Port]:
        return {self.PORT_TTS_OUTPUT: Port(self.PORT_TTS_OUTPUT)}

    def run(self):
        self._init_app()
        while self.running:
            item: Optional[LLMDialogMessage] = None
            try:
                item = self.tts_queue.get()
                if item is None:
                    break
                with tracker.track("TTS dispatch"):
                    self.tts_message_dispatcher.dispatch(item)
            except Exception as e:
                print(f"TTSWorker: 任务处理失败: {e}")
                traceback.print_exc()
                if item is not None:
                    self.put_data(
                        get_app_runtime().opencc.convert(item.name),
                        item.text,
                        str(item.asset_id) if item.asset_id is not None else "-1",
                        "",
                        is_system_message=False,
                        effect=item.effect,
                    )

    def stop(self):
        self.running = False
        self.tts_queue.put(None)
        super().stop()

class UIWorker(QThreadDagNode):
    PORT_TTS_OUTPUT = "tts_output"
    DIALOG_CHANNEL_ID = 7

    def __init__(
        self,
        input_queue: Queue[TTSOutputMessage] | None = None,
        parent=None,
        *,
        name: str = "ui_worker",
    ):
        super().__init__(name, parent=parent)
        self._app_inited = False
        self.audio_path_queue = input_queue
        self.task_done_requested = threading.Event()
        self.current_audio_path = None
        self.DIALOG_CHANNEL_ID = 7
        self.ui_out_dispatcher = default_ui_output_handler_chain()
        if input_queue is not None:
            self.bind_input(self.PORT_TTS_OUTPUT, input_queue)

    def _init_app(self):
        if self._app_inited:
            return
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.audio_path_queue = self.inq(self.PORT_TTS_OUTPUT)
        self._init_channel()
        br = get_app_runtime().ui_playback
        br.task_done_requested = self.task_done_requested
        br.dialog_channel = self.dialog_channel
        self.ui_out_dispatcher.init_handlers()
        self._app_inited = True

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_TTS_OUTPUT: Port(self.PORT_TTS_OUTPUT)}

    def outputs(self) -> dict[str, Port]:
        return {}

    def _init_channel(self):
        try:
            pygame.mixer.init()
            if pygame.mixer.get_num_channels() < self.DIALOG_CHANNEL_ID + 1:
                pygame.mixer.set_num_channels(self.DIALOG_CHANNEL_ID + 1)
            self.dialog_channel: pygame.mixer.Channel = pygame.mixer.Channel(self.DIALOG_CHANNEL_ID)
            print(f"UIWorker: 对话播放通道初始化成功，使用通道 {self.DIALOG_CHANNEL_ID}")
        except Exception as e:
            print(f"UIWorker: Pygame Mixer 初始化或通道获取失败: {e}")
            self.dialog_channel = None

    def skip_speech(self):
        if self.audio_path_queue.empty():
            return
        if self.dialog_channel and self.dialog_channel.get_busy():
            self.dialog_channel.stop()
        self.current_audio_path = None
        get_app_runtime().ui_playback.current_audio_path = None
        self.task_done_requested.set()

    def run(self):
        self._init_app()
        while self.running:
            try:
                self.task_done_requested.clear()
                output_data: TTSOutputMessage = self.audio_path_queue.get()
                if output_data is None:
                    break
                self.ui_out_dispatcher.dispatch(output_data)
            except Exception as e:
                traceback.print_exc()
                print(f"UIWorker: 任务处理失败: {e}")
                try:
                    self.ui_update_manager.post_notification(f"界面更新失败: {e}")
                except Exception:
                    pass
                if not self.task_done_requested.is_set():
                    _text = getattr(output_data, "text", "") or ""
                    wait = max(len(_text) / 10, 0.3) if _text else 0.3
                    self.task_done_requested.wait(timeout=wait)
                self.audio_path_queue.task_done()

    def stop(self):
        self.running = False
        self.task_done_requested.set()
        self.audio_path_queue.put(None)
        super().stop()
