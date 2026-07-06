import re
from pathlib import Path
from typing import Optional

from i18n import tr
from sdk.logging import get_logger, log_context, new_log_id
from sdk.logging.timing import tracker
from sdk.exception.types import classify_exception
from sdk.exception.presenter import format_llm_exception_message

from queue import Queue, Empty

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

logger = get_logger(__name__)

# --- QThread + DagNode 基类 ---

class _CancelAwareQueue:
    """Delegate queue operations, but drop new outputs after cancellation."""

    def __init__(self, queue, *cancel_events: threading.Event | None) -> None:
        self._queue = queue
        self._cancel_events = tuple(event for event in cancel_events if event is not None)

    def _cancelled(self) -> bool:
        return any(event.is_set() for event in self._cancel_events)

    def put(self, *args, **kwargs):
        if self._cancelled():
            return None
        return self._queue.put(*args, **kwargs)

    def put_nowait(self, item):
        return self.put(item, block=False)

    def __getattr__(self, name: str):
        return getattr(self._queue, name)


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


def _format_llm_worker_error(exc: BaseException) -> str:
    return format_llm_exception_message(exc, fallback_message=tr("desktop.llm_parse_empty"))


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
            got_item = False
            turn_scope = None
            try:
                message: UserInputMessage = self.user_input_queue.get()
                got_item = True
                if message is None:
                    break

                rt = get_app_runtime()
                rt.cancellation_requested.clear()
                rt.generating.set()

                if rt.cancellation_requested.is_set():
                    continue

                turn_scope = log_context(turn_id=new_log_id("turn_"))
                turn_scope.__enter__()
                logger.info(
                    "LLM worker processing user message",
                    extra={
                        "event": "chat.turn.started",
                        "input_chars": len(message.text or ""),
                    },
                )
                tracker.start_cross("e2e")
                self.ui_update_manager.post_notification("发送成功，正在等待回复中...")

                if hasattr(self.ui_update_manager, "record_user_message"):
                    self.ui_update_manager.record_user_message(message.text)
                else:
                    formatted_user_message = (
                        "<p style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                        f"<b style='color:white;'>你</b>: {message.text}</p>"
                    )
                    self.ui_update_manager.chat_history.append(formatted_user_message)

                is_streaming = get_app_runtime().config.config.api_config.is_streaming
                with tracker.track("LLM chat total"):
                    raw_response = self.llm_manager.chat(message.text, stream=is_streaming)

                if rt.cancellation_requested.is_set():
                    # chat() returned early due to cancel — skip parse / persist
                    continue

                if is_streaming:
                    response_stream = raw_response
                else:
                    response_stream = [raw_response]

                parser = LlmResponseStreamParser()
                reasoning_shown = ""
                message_count = 0
                raw_chunks: list = []

                with tracker.track("LLM stream parse"):
                    for chunk in response_stream:
                        if rt.cancellation_requested.is_set():
                            break
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
                        raw_chunks.append(chunk_message)
                        for llm_dialog in parser.feed(chunk_message):
                            message_count += 1
                            self.tts_queue.put(llm_dialog)

                # --- Interrupted: write committed context, discard the rest ---
                if rt.cancellation_requested.is_set():
                    total_raw = "".join(raw_chunks)
                    buf: str = getattr(parser, "buffer", "") or ""
                    buf = buf.strip()
                    if buf and total_raw.endswith(buf):
                        committed_raw = total_raw[: len(total_raw) - len(buf)]
                    else:
                        committed_raw = total_raw
                    if committed_raw.strip():
                        try:
                            self.llm_manager.add_message("assistant", committed_raw.strip())
                        except Exception:
                            pass
                    continue

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

            except Exception as e:
                error_info = classify_exception(e)
                logger.exception(
                    "LLM worker task failed",
                    extra={
                        "event": "llm.worker.failed",
                        "error_kind": error_info["kind"] if error_info else "",
                        "http_status_code": error_info.get("statusCode") if error_info else None,
                        "http_url": error_info.get("url", "") if error_info else "",
                        "http_timeout": error_info.get("timeout") if error_info else None,
                    },
                )
                try:
                    from sdk.messages import TTSOutputMessage
                    _err = _format_llm_worker_error(e)
                    get_app_runtime().audio_path_queue.put(TTSOutputMessage(
                        audio_path="", name="system", asset_id="-1",
                        text=_err, is_system_message=True, effect="",
                    ))
                except Exception:
                    pass
            finally:
                # Do NOT clear generating here — TTS / UI playback continues
                # after LLM finishes.  UIWorker clears it when the pipeline is
                # truly idle (audio_path_queue empty + no audio playing).
                if turn_scope is not None:
                    turn_scope.__exit__(None, None, None)
                if got_item:
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
        self._cancel_event = threading.Event()          # 新增：取消当前合成用
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

    def put_data(self, character_name: str, speech: str, sprite: str, audio_path,
                 is_system_message: bool = False, effect: str = ""):
        """与 handler 中 tts_emit_to_ui_queue 一致，供本 worker 异常路径使用。"""
        tts_emit_to_ui_queue(
            character_name, speech, sprite, audio_path or "",
            is_system_message=is_system_message, effect=effect,
        )

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_LLM_OUTPUT: Port(self.PORT_LLM_OUTPUT)}

    def outputs(self) -> dict[str, Port]:
        return {self.PORT_TTS_OUTPUT: Port(self.PORT_TTS_OUTPUT)}

    def start(self) -> None:
        if self.isRunning():
            return
        self._cancel_event.clear()
        super().start()

    def _dispatch_with_cancel(self, item):
        """
        在 daemon 子线程中执行 dispatcher.dispatch，主线程等待完成或取消。
        - worker stop 或 runtime interrupt 取消时，直接返回，不等待子线程。
        - 子线程异常会被捕获并在主线程重新抛出，保持原有异常处理路径。
        """
        done = threading.Event()
        error = [None]
        rt = try_get_app_runtime()
        runtime_cancel_event = getattr(rt, "cancellation_requested", None) if rt is not None else None

        def cancelled() -> bool:
            return self._cancel_event.is_set() or bool(
                runtime_cancel_event is not None and runtime_cancel_event.is_set()
            )

        def work():
            original_audio_queue = None
            guarded_audio_queue = None
            try:
                if rt is not None:
                    original_audio_queue = rt.audio_path_queue
                    guarded_audio_queue = _CancelAwareQueue(
                        original_audio_queue,
                        self._cancel_event,
                        runtime_cancel_event,
                    )
                    rt.audio_path_queue = guarded_audio_queue
                if cancelled():
                    return
                self.tts_message_dispatcher.dispatch(item)
            except Exception as e:
                if not cancelled():
                    error[0] = e
            finally:
                if (
                    rt is not None
                    and guarded_audio_queue is not None
                    and rt.audio_path_queue is guarded_audio_queue
                ):
                    rt.audio_path_queue = original_audio_queue
                done.set()

        t = threading.Thread(target=work, daemon=True)
        t.start()

        while not done.is_set() and not cancelled():
            t.join(timeout=0.1)

        if cancelled() and not done.is_set():
            return

        if error[0] is not None:
            raise error[0]

    def run(self):
        self._init_app()
        while self.running:
            item: Optional[LLMDialogMessage] = None
            got_item = False
            try:
                item = self.tts_queue.get()
                got_item = True
                if item is None:
                    break
                if get_app_runtime().cancellation_requested.is_set():
                    continue
                with tracker.track("TTS dispatch"):
                    self._dispatch_with_cancel(item)
                if get_app_runtime().cancellation_requested.is_set():
                    self.audio_path_queue.clear()
            except Exception as e:
                logger.exception("TTS worker task failed", extra={"event": "tts.worker.failed"})
                if item is not None:
                    self.put_data(
                        get_app_runtime().opencc.convert(item.name),
                        item.text,
                        str(item.asset_id) if item.asset_id is not None else "-1",
                        "",
                        is_system_message=False,
                        effect=item.effect,
                    )
            finally:
                if got_item:
                    self.tts_queue.task_done()

    def stop(self):
        self._cancel_event.set()        # 通知取消当前合成
        self.running = False
        self.tts_queue.put(None)        # 唤醒 queue.get()
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
        self._dialog_active = False
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
        runtime = get_app_runtime()
        playback = runtime.ui_playback
        current_audio_path = self.current_audio_path or getattr(playback, "current_audio_path", None)
        dialog_channel_busy = bool(self.dialog_channel and self.dialog_channel.get_busy())
        active_dialog = self._dialog_active and not self.task_done_requested.is_set()
        audio_active = dialog_channel_busy or bool(current_audio_path)
        if not audio_active and not active_dialog:
            return
        if dialog_channel_busy:
            self.dialog_channel.stop()
        if audio_active:
            self.current_audio_path = None
            playback.current_audio_path = None
            ui_updates = getattr(self, "ui_update_manager", None) or runtime.ui_update_manager
            if hasattr(ui_updates, "post_tts_skip"):
                ui_updates.post_tts_skip()
        self.task_done_requested.set()

    def run(self):
        self._init_app()
        idle_count = 0
        while self.running:
            output_data: Optional[TTSOutputMessage] = None
            got_item = False
            try:
                self.task_done_requested.clear()
                try:
                    output_data = self.audio_path_queue.get(timeout=0.4)
                    got_item = True
                    idle_count = 0
                except Empty:
                    # Timeout — check if the full pipeline is now idle
                    idle_count += 1
                    if idle_count >= 12:  # ~5 s of silence
                        rt = get_app_runtime()
                        if rt.tts_queue.empty() and rt.audio_path_queue.empty():
                            busy = self.dialog_channel is not None and self.dialog_channel.get_busy()
                            if not busy:
                                rt.generating.clear()
                                idle_count = 0
                    continue

                if output_data is None:
                    break
                if get_app_runtime().cancellation_requested.is_set():
                    continue
                self._dialog_active = True
                self.ui_out_dispatcher.dispatch(output_data)
            except Exception as e:
                logger.exception("UI worker task failed", extra={"event": "ui.worker.failed"})
                try:
                    self.ui_update_manager.post_notification(f"界面更新失败: {e}")
                except Exception:
                    pass
                if not self.task_done_requested.is_set():
                    _text = getattr(output_data, "text", "") or ""
                    wait = max(len(_text) / 10, 0.3) if _text else 0.3
                    self.task_done_requested.wait(timeout=wait)
            finally:
                self._dialog_active = False
                if got_item:
                    self.audio_path_queue.task_done()

    def stop(self):
        self.running = False
        self.task_done_requested.set()
        self.audio_path_queue.put(None)
        super().stop()


class HeadlessSinkNode(QThreadDagNode):
    """Consumes TTS output messages silently; no audio, no UI, no pygame.

    Intended as the terminal node in ``headless.yaml`` so that
    ``--headless`` mode avoids dragging in UIWorker / pygame audio channels.
    """

    PORT_TTS_OUTPUT = "tts_output"

    def __init__(
        self,
        input_queue: Queue[TTSOutputMessage] | None = None,
        parent=None,
        *,
        name: str = "headless_sink",
    ):
        super().__init__(name, parent=parent)
        self.audio_path_queue = input_queue
        if input_queue is not None:
            self.bind_input(self.PORT_TTS_OUTPUT, input_queue)

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_TTS_OUTPUT: Port(self.PORT_TTS_OUTPUT)}

    def outputs(self) -> dict[str, Port]:
        return {}

    def _init_app(self):
        if getattr(self, "_app_inited", False):
            return
        self.audio_path_queue = self.inq(self.PORT_TTS_OUTPUT)
        self._app_inited = True

    def run(self):
        self._init_app()
        while self.running:
            item: Optional[TTSOutputMessage] = None
            got_item = False
            try:
                item = self.audio_path_queue.get()
                got_item = True
                if item is None:
                    break
                if getattr(item, "text", ""):
                    print(f"[headless] {item.name}: {item.text}")
            except Exception:
                pass
            finally:
                if got_item:
                    self.audio_path_queue.task_done()

    def stop(self):
        self.running = False
        self.audio_path_queue.put(None)
        super().stop()
