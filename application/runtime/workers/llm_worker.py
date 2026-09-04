"""Worker that turns user input into streamed dialog messages."""

import re
from queue import Queue

from ai.vision.service import ChatVisionService
from core.media.chat_attachments import resolve_chat_attachments
from core.messaging.dialog_reconciliation import reconcile_dialog_repair
from core.messaging.stream_events import (
    STREAM_DIALOG_REPAIR_KEY,
    STREAM_REASONING_DELTA_KEY,
)
from core.messaging.stream_parser import LlmResponseStreamParser
from i18n import tr
from sdk.exception.presenter import format_llm_exception_message
from sdk.exception.types import classify_exception
from sdk.graph import Port
from sdk.logging import get_logger, log_context, new_log_id
from sdk.logging.timing import tracker
from sdk.messages import LLMDialogMessage, UserInputMessage

from ..context import get_app_runtime
from .base import ThreadDagNode

logger = get_logger(__name__)


_RAIN_STOP_INPUT_RE = re.compile(
    r"^\s*[（(]?\s*(?:"
    r"(?:(?:现在|外面)的?雨|雨声|雨)\s*(?:已经)?(?:停下来了|停了|不下了)"
    r"|不下雨了)\s*[）)]?\s*[。！？!?]*\s*$"
)


def _stop_rain_for_explicit_user_input(text: str, ui_updates) -> bool:
    """Stop the active rain loop for a direct player state change, before LLM output."""
    if not _RAIN_STOP_INPUT_RE.fullmatch(str(text or "")):
        return False
    return bool(ui_updates.resolve_effect("stop:雨天", {}, after_dialog=False))


def _busy_preview_reasoning(raw: str, max_len: int = 200) -> str:
    """压成单行摘要供底栏显示（与 ui_message_handler 中 COT 预览一致）。"""
    s = re.sub(r"<[^>]+>", " ", raw or "")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _format_llm_worker_error(exc: BaseException) -> str:
    return format_llm_exception_message(
        exc, fallback_message=tr("desktop.llm_parse_empty")
    )


class LLMWorker(ThreadDagNode):
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
        self.chat_vision_service = ChatVisionService()
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
            turn = None
            try:
                message: UserInputMessage = self.user_input_queue.get()
                got_item = True
                if message is None:
                    break

                rt = get_app_runtime()
                turn = rt.chat_turn_service.begin_turn()

                if turn.is_cancelled():
                    continue

                turn_scope = log_context(turn_id=new_log_id("turn_"))
                turn_scope.__enter__()
                attachments = resolve_chat_attachments(message.attachments)
                prepared_input = self.chat_vision_service.prepare(
                    message.text,
                    attachments,
                    adapter=self.llm_manager.llm_adapter,
                )
                logger.info(
                    "LLM worker processing user message",
                    extra={
                        "event": "chat.turn.started",
                        "input_chars": len(message.text or ""),
                        "attachment_count": len(attachments),
                        "vision_mode": prepared_input.mode,
                    },
                )
                tracker.start_cross("e2e")
                self.ui_update_manager.post_notification("发送成功，正在等待回复中...")
                _stop_rain_for_explicit_user_input(message.text, self.ui_update_manager)

                if hasattr(self.ui_update_manager, "record_user_message"):
                    self.ui_update_manager.record_user_message(
                        prepared_input.display_text
                    )
                else:
                    formatted_user_message = (
                        "<p style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                        f"<b style='color:white;'>你</b>: {prepared_input.display_text}</p>"
                    )
                    self.ui_update_manager.chat_history.append(formatted_user_message)

                is_streaming = get_app_runtime().config.config.api_config.is_streaming
                with tracker.track("LLM chat total"):
                    chat_kwargs = {
                        "stream": is_streaming,
                        "dialog_output_required": True,
                        "user_input_text": message.text,
                        "user_attachments": [
                            attachment.to_payload() for attachment in attachments
                        ],
                    }
                    if attachments:
                        chat_kwargs["user_display_text"] = prepared_input.display_text
                    raw_response = self.llm_manager.chat(
                        prepared_input.content, **chat_kwargs
                    )

                if turn.is_cancelled():
                    # chat() returned early due to cancel — skip parse / persist
                    continue

                if is_streaming:
                    response_stream = raw_response
                else:
                    response_stream = [raw_response]

                parser = LlmResponseStreamParser()
                reasoning_shown = ""
                message_count = 0
                delivered_dialogs: list[LLMDialogMessage] = []
                raw_chunks: list = []

                with tracker.track("LLM stream parse"):
                    for chunk in response_stream:
                        if turn.is_cancelled():
                            break
                        if (
                            isinstance(chunk, dict)
                            and STREAM_REASONING_DELTA_KEY in chunk
                        ):
                            reasoning_shown += chunk[STREAM_REASONING_DELTA_KEY]
                            preview = _busy_preview_reasoning(reasoning_shown)
                            label = tr("desktop.thinking_busy_prefix")
                            bar_text = f"{label} · {preview}" if preview else label
                            self.ui_update_manager.post_busy_bar(bar_text, 0.0)
                            continue
                        if (
                            isinstance(chunk, dict)
                            and STREAM_DIALOG_REPAIR_KEY in chunk
                        ):
                            repaired_parser = LlmResponseStreamParser()
                            repaired_messages = list(
                                repaired_parser.feed(chunk[STREAM_DIALOG_REPAIR_KEY])
                            )
                            delivered_before_repair = message_count
                            reconciliation = reconcile_dialog_repair(
                                delivered_dialogs,
                                repaired_messages,
                            )
                            appended_messages = 0
                            for llm_dialog in reconciliation.messages_to_append:
                                message_count += 1
                                appended_messages += 1
                                delivered_dialogs.append(llm_dialog)
                                self.tts_queue.put(
                                    llm_dialog.model_copy(update={"turn_id": turn.id})
                                )
                            logger.info(
                                "Reconciled repaired dialogue with streamed messages",
                                extra={
                                    "event": "llm.dialog_format.repair_reconciled",
                                    "streamed_messages": delivered_before_repair,
                                    "repaired_messages": len(repaired_messages),
                                    "appended_messages": appended_messages,
                                    "streamed_prefix_matched": reconciliation.prefix_matched,
                                },
                            )
                            continue
                        chunk_message = (
                            chunk
                            if isinstance(chunk, str)
                            else str(chunk)
                            if chunk is not None
                            else ""
                        )
                        raw_chunks.append(chunk_message)
                        for llm_dialog in parser.feed(chunk_message):
                            message_count += 1
                            delivered_dialogs.append(llm_dialog)
                            self.tts_queue.put(
                                llm_dialog.model_copy(update={"turn_id": turn.id})
                            )

                # --- Interrupted: write committed context, discard the rest ---
                if turn.is_cancelled():
                    total_raw = "".join(raw_chunks)
                    buf: str = getattr(parser, "buffer", "") or ""
                    buf = buf.strip()
                    if buf and total_raw.endswith(buf):
                        committed_raw = total_raw[: len(total_raw) - len(buf)]
                    else:
                        committed_raw = total_raw
                    if committed_raw.strip():
                        try:
                            self.llm_manager.add_message(
                                "assistant", committed_raw.strip()
                            )
                        except Exception:
                            pass
                    continue

                if message_count == 0:
                    _msg = tr("desktop.llm_parse_empty")
                    if parser.has_errors:
                        _msg += "\n" + parser.last_error
                    elif parser.unparsed_remainder:
                        _msg += "\n" + tr(
                            "desktop.llm_parse_remainder",
                            text=parser.unparsed_remainder,
                        )
                    logger.error(
                        "LLM response contained no valid dialogue messages",
                        extra={
                            "event": "llm.dialog_format.invalid",
                            "parse_failures": parser.parse_failures,
                            "raw_chars": len(parser.accumulated_text),
                            "raw_preview": parser.accumulated_text[:500],
                            "unparsed_remainder": parser.unparsed_remainder,
                        },
                    )
                    self.ui_update_manager.post_busy_bar(_msg, 0.0)
                    from sdk.messages import TTSOutputMessage

                    get_app_runtime().audio_path_queue.put(
                        TTSOutputMessage(
                            audio_path="",
                            name="system",
                            asset_id="-1",
                            text=_msg,
                            is_system_message=True,
                            effect="",
                        )
                    )
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
                        "http_status_code": error_info.get("statusCode")
                        if error_info
                        else None,
                        "http_url": error_info.get("url", "") if error_info else "",
                        "http_timeout": error_info.get("timeout")
                        if error_info
                        else None,
                    },
                )
                try:
                    from sdk.messages import TTSOutputMessage

                    _err = _format_llm_worker_error(e)
                    get_app_runtime().audio_path_queue.put(
                        TTSOutputMessage(
                            audio_path="",
                            name="system",
                            asset_id="-1",
                            text=_err,
                            is_system_message=True,
                            effect="",
                        )
                    )
                except Exception:
                    pass
            finally:
                if turn is not None:
                    get_app_runtime().chat_turn_service.mark_generation_complete(turn)
                if turn_scope is not None:
                    turn_scope.__exit__(None, None, None)
                if got_item:
                    self.user_input_queue.task_done()

    def stop(self):
        self.running = False
        self.user_input_queue.put(None)
        super().stop()
