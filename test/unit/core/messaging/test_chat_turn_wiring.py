from __future__ import annotations

from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.messaging.chat_turn_wiring import create_chat_turn_service
from core.messaging.queue import ClearableQueue


def make_config(*, interrupt_enabled: bool, batch_enabled: bool = False) -> object:
    return SimpleNamespace(
        config=SimpleNamespace(
            api_config=SimpleNamespace(
                interrupt_enabled=interrupt_enabled,
                is_batch_input_enabled=batch_enabled,
                batch_input_timeout=5.0,
                batch_input_separator="\n---\n",
            )
        )
    )


def test_wiring_honors_disabled_interrupt_option() -> None:
    input_queue = Queue()
    llm_manager = MagicMock()
    service = create_chat_turn_service(
        config=make_config(interrupt_enabled=False),
        user_input_queue=input_queue,
        tts_queue=ClearableQueue(),
        audio_queue=ClearableQueue(),
        llm_manager=llm_manager,
        ui_worker=MagicMock(),
        ui_updates=MagicMock(),
    )
    turn = service.begin_turn()

    service.submit("next")

    assert not turn.is_cancelled()
    llm_manager.cancel_current_chat.assert_not_called()
    assert input_queue.get_nowait().text == "next"


def test_wiring_preserves_attachment_payloads() -> None:
    input_queue = Queue()
    service = create_chat_turn_service(
        config=make_config(interrupt_enabled=False),
        user_input_queue=input_queue,
        tts_queue=ClearableQueue(),
        audio_queue=ClearableQueue(),
        llm_manager=MagicMock(),
        ui_worker=MagicMock(),
        ui_updates=MagicMock(),
    )
    attachments = [{"kind": "file", "name": "notes.txt", "path": "C:/notes.txt"}]

    service.submit("read", attachments=attachments)

    message = input_queue.get_nowait()
    assert message.text == "read"
    assert message.attachments == attachments


def test_wiring_clears_downstream_ports_on_interrupt() -> None:
    input_queue = Queue()
    tts_queue = ClearableQueue()
    audio_queue = ClearableQueue()
    llm_manager = MagicMock()
    ui_worker = MagicMock()
    ui_updates = MagicMock()
    tts_queue.put("pending tts")
    audio_queue.put("pending audio")
    service = create_chat_turn_service(
        config=make_config(interrupt_enabled=True),
        user_input_queue=input_queue,
        tts_queue=tts_queue,
        audio_queue=audio_queue,
        llm_manager=llm_manager,
        ui_worker=ui_worker,
        ui_updates=ui_updates,
    )
    old_turn = service.begin_turn()

    service.submit("next")

    assert old_turn.is_cancelled()
    assert tts_queue.empty()
    assert audio_queue.empty()
    llm_manager.cancel_current_chat.assert_called_once_with()
    ui_worker.skip_speech.assert_called_once_with()
    ui_updates.hide_busy_bar.assert_called_once_with()
    assert input_queue.get_nowait().text == "next"


def test_wiring_clears_flushed_batch_delivery_when_batch_is_cancelled() -> None:
    input_queue = ClearableQueue()
    service = create_chat_turn_service(
        config=make_config(interrupt_enabled=False, batch_enabled=True),
        user_input_queue=input_queue,
        tts_queue=ClearableQueue(),
        audio_queue=ClearableQueue(),
        llm_manager=MagicMock(),
        ui_worker=MagicMock(),
        ui_updates=MagicMock(),
    )
    service.submit("stale branch input")
    service.flush()
    assert not input_queue.empty()

    service.cancel_pending_batch()

    assert input_queue.empty()
