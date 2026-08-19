from queue import Queue

from core.messaging.chat_turn_service import ChatTurnService
from application.chat.spoken_dialog import enqueue_spoken_dialog_lines
from sdk.messages import LLMDialogMessage


def test_enqueue_spoken_dialog_lines_starts_a_tts_turn() -> None:
    tts_queue = Queue()
    service = ChatTurnService()

    queued = enqueue_spoken_dialog_lines(
        tts_queue,
        service,
        [
            {"name": "绫", "text": "今晚有空吗？", "sprite": "02"},
            {"name": "", "text": "skip"},
            {"name": "NARR", "text": ""},
        ],
    )

    assert queued == 1
    message = tts_queue.get_nowait()
    assert isinstance(message, LLMDialogMessage)
    assert message.name == "绫"
    assert message.text == "今晚有空吗？"
    assert message.asset_id == "02"
    assert message.audio_only is True
    assert message.turn_id == service.current_turn().id
    assert service.current_turn().generation_complete.is_set()
    assert tts_queue.empty()


def test_enqueue_spoken_dialog_lines_interrupts_an_active_turn() -> None:
    tts_queue = Queue()
    service = ChatTurnService()
    previous = service.begin_turn()

    enqueue_spoken_dialog_lines(
        tts_queue,
        service,
        [{"name": "绫", "text": "换一句。"}],
    )

    assert previous.is_cancelled()
    assert service.current_turn().id != previous.id
    assert tts_queue.get_nowait().turn_id == service.current_turn().id
