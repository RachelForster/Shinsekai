from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTextEdit, QWidget

from core.messaging.chat_turn_service import ChatTurnOptions, ChatTurnService
from ui.chat_ui.chat_turn_controller import ChatTurnController


class FakeChatWindow(QWidget):
    flush_batch = Signal()
    input_composition_started = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.input_box = QTextEdit(self)


def test_controller_keeps_qt_state_out_of_the_core_service(qtbot) -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=30,
        ),
    )
    service.submit("first")
    window = FakeChatWindow()
    qtbot.addWidget(window)
    ui_updates = MagicMock()
    controller = ChatTurnController(window, service, ui_updates)

    window.input_box.setPlainText("typing")
    assert service.batch_state().typing
    ui_updates.post_busy_bar.assert_called()

    window.flush_batch.emit()
    assert delivered == ["first"]
    assert service.batch_state().pending_count == 0

    controller.deleteLater()
    service.close()
