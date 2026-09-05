"""Resolve dialog messages into presentation-ready media."""

import threading
from queue import Queue
from typing import Optional

from application.chat.dialog_media import (
    ConfigSpriteLookupStrategy,
    SpriteLookupStrategy,
    TtsGenerationStrategy,
)
from application.chat.handlers.registry import default_dialog_media_handler_chain
from sdk.graph import Port
from sdk.logging import get_logger
from sdk.logging.timing import tracker
from sdk.messages import LLMDialogMessage, PresentationMessage

from ..context import emit_presentation_message, get_app_runtime, try_get_app_runtime
from .base import ThreadDagNode

logger = get_logger(__name__)


class _CancelAwareQueue:
    """Delegate queue operations, but drop new outputs after cancellation."""

    def __init__(self, queue, *cancel_events: threading.Event | None) -> None:
        self._queue = queue
        self._cancel_events = tuple(
            event for event in cancel_events if event is not None
        )

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


class DialogMediaWorker(ThreadDagNode):
    PORT_DIALOG = "dialog"
    PORT_PRESENTATION = "presentation"

    def __init__(
        self,
        input_queue: Queue[LLMDialogMessage] | None = None,
        output_queue: Queue[PresentationMessage] | None = None,
        parent=None,
        *,
        name: str = "dialog_media_worker",
        sprite_lookup_strategy: SpriteLookupStrategy | None = None,
        tts_generation_strategy: TtsGenerationStrategy | None = None,
    ):
        super().__init__(name, parent=parent)
        self._app_inited = False
        self.dialog_queue = input_queue
        self.presentation_queue = output_queue
        self.dialog_media_dispatcher = None
        self.sprite_lookup_strategy = sprite_lookup_strategy
        self.tts_generation_strategy = tts_generation_strategy
        self._cancel_event = threading.Event()
        if input_queue is not None:
            self.bind_input(self.PORT_DIALOG, input_queue)
        if output_queue is not None:
            self.bind_output(self.PORT_PRESENTATION, output_queue)

    def _init_app(self):
        if self._app_inited:
            return
        self.dialog_queue = self.inq(self.PORT_DIALOG)
        self.presentation_queue = self.outq(self.PORT_PRESENTATION)
        rt = try_get_app_runtime()
        runtime_strategy = getattr(rt, "sprite_lookup_strategy", None)
        if self.sprite_lookup_strategy is None:
            self.sprite_lookup_strategy = runtime_strategy
        if self.sprite_lookup_strategy is None:
            self.sprite_lookup_strategy = ConfigSpriteLookupStrategy()
        if rt is not None:
            rt.sprite_lookup_strategy = self.sprite_lookup_strategy
        self.dialog_media_dispatcher = default_dialog_media_handler_chain(
            sprite_lookup_strategy=self.sprite_lookup_strategy,
            tts_generation_strategy=self.tts_generation_strategy,
        )
        self.dialog_media_dispatcher.init_handlers()
        self._app_inited = True

    def _emit_fallback(
        self,
        character_name: str,
        speech: str,
        sprite: str,
        audio_path,
        is_system_message: bool = False,
        effect: str = "",
    ):
        """Keep the original dialog visible when media preparation fails."""
        emit_presentation_message(
            character_name,
            speech,
            sprite,
            audio_path or "",
            is_system_message=is_system_message,
            effect=effect,
        )

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_DIALOG: Port(self.PORT_DIALOG)}

    def outputs(self) -> dict[str, Port]:
        return {self.PORT_PRESENTATION: Port(self.PORT_PRESENTATION)}

    def start(self) -> None:
        if self.isRunning():
            return
        self._cancel_event.clear()
        super().start()

    def _dispatch_with_cancel(self, item, turn=None):
        """
        在 daemon 子线程中执行 dispatcher.dispatch，主线程等待完成或取消。
        - worker stop 或 runtime interrupt 取消时，直接返回，不等待子线程。
        - 子线程异常会被捕获并在主线程重新抛出，保持原有异常处理路径。
        """
        done = threading.Event()
        error = [None]
        rt = try_get_app_runtime()
        if turn is None and rt is not None:
            turn = rt.chat_turn_service.current_turn()
        runtime_cancel_event = getattr(turn, "cancelled", None)

        def cancelled() -> bool:
            return self._cancel_event.is_set() or bool(
                runtime_cancel_event is not None and runtime_cancel_event.is_set()
            )

        def work():
            original_presentation_queue = None
            guarded_presentation_queue = None
            try:
                if rt is not None:
                    original_presentation_queue = rt.presentation_queue
                    guarded_presentation_queue = _CancelAwareQueue(
                        original_presentation_queue,
                        self._cancel_event,
                        runtime_cancel_event,
                    )
                    rt.presentation_queue = guarded_presentation_queue
                if cancelled():
                    return
                self.dialog_media_dispatcher.dispatch(item)
            except Exception as e:
                if not cancelled():
                    error[0] = e
            finally:
                if (
                    rt is not None
                    and guarded_presentation_queue is not None
                    and rt.presentation_queue is guarded_presentation_queue
                ):
                    rt.presentation_queue = original_presentation_queue
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
            turn = None
            got_item = False
            try:
                item = self.dialog_queue.get()
                got_item = True
                if item is None:
                    break
                turn = get_app_runtime().chat_turn_service.current_turn()
                item_turn_id = getattr(item, "turn_id", None)
                if item_turn_id is not None and item_turn_id != turn.id:
                    continue
                if turn.is_cancelled():
                    continue
                with tracker.track("Dialog media dispatch"):
                    self._dispatch_with_cancel(item, turn)
                if turn.is_cancelled():
                    self.presentation_queue.clear()
            except Exception:
                logger.exception(
                    "dialog media worker task failed",
                    extra={"event": "dialog_media.worker.failed"},
                )
                current_turn = get_app_runtime().chat_turn_service.current_turn()
                if (
                    item is not None
                    and turn is not None
                    and turn.id == current_turn.id
                    and not turn.is_cancelled()
                ):
                    self._emit_fallback(
                        get_app_runtime().opencc.convert(item.name),
                        item.text,
                        str(item.asset_id) if item.asset_id is not None else "-1",
                        "",
                        is_system_message=False,
                        effect=item.effect,
                    )
            finally:
                if got_item:
                    self.dialog_queue.task_done()

    def stop(self):
        self._cancel_event.set()
        self.running = False
        self.dialog_queue.put(None)  # 唤醒 queue.get()
        super().stop()
