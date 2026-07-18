"""Qt adapter for :mod:`core.messaging.chat_turn_service`."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer

from core.messaging.chat_turn_service import BatchState, ChatTurnService


class ChatTurnController(QObject):
    """Translate Qt input events into presentation-neutral service calls."""

    def __init__(self, window: Any, service: ChatTurnService, ui_updates: Any) -> None:
        super().__init__(window)
        self._window = window
        self._service = service
        self._ui_updates = ui_updates
        self._composing = False
        self._showing_batch_status = False
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh)

        window.input_box.textChanged.connect(self._on_text_changed)
        window.input_composition_started.connect(self._on_composition_started)
        window.flush_batch.connect(self._flush)

    def _on_text_changed(self) -> None:
        has_text = bool(self._window.input_box.toPlainText().strip())
        if has_text:
            self._composing = False
        state = self._service.input_changed(has_text=has_text, composing=self._composing)
        self._render(state)

    def _on_composition_started(self) -> None:
        self._composing = True
        state = self._service.input_changed(has_text=False, composing=True)
        self._render(state)

    def _flush(self) -> None:
        self._composing = False
        self._render(self._service.flush())

    def _refresh(self) -> None:
        self._render(self._service.batch_state())

    def _render(self, state: BatchState) -> None:
        if state.pending_count <= 0:
            self._timer.stop()
            if self._showing_batch_status:
                self._ui_updates.hide_busy_bar()
                self._showing_batch_status = False
            return

        if state.typing:
            text = "[正在输入…]"
        elif state.scheduled and state.remaining_seconds is not None:
            text = f"[正在输入…{state.remaining_seconds}]"
        else:
            text = "[正在输入…]"

        self._ui_updates.post_busy_bar(text, 0.0)
        self._showing_batch_status = True
        if not self._timer.isActive():
            self._timer.start()
