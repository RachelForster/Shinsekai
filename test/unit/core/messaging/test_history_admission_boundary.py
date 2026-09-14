from core.messaging.chat_turn_service import ChatTurnOptions, ChatTurnService
from threading import Event, Thread
import pytest


def test_history_boundary_cancels_begun_turn_and_rejects_already_dequeued_input():
    delivered = []
    service = ChatTurnService(revision_sink=lambda *args: delivered.append(args))
    service.submit("old", defer_until_idle=True)
    old = delivered.pop()
    begun = service.begin_turn(expected_revision=old[2])
    with service.history_boundary():
        assert begun.is_cancelled()
    late = service.begin_turn(expected_revision=old[2])
    assert late.is_cancelled()
    assert not service.is_active()
    service.submit("fresh", defer_until_idle=True)
    fresh = delivered.pop()
    assert not service.begin_turn(expected_revision=fresh[2]).is_cancelled()


def test_retired_asr_already_dequeued_does_not_block_manual_or_next_voice():
    delivered = []
    service = ChatTurnService(revision_sink=lambda *args: delivered.append(args))
    service.submit("voice", defer_until_idle=True, utterance_id="u1")
    old = delivered.pop()
    service.submit("edited voice", replace_utterance_id="u1", interrupt_current=False)
    manual = delivered.pop()
    assert service.begin_turn(expected_revision=old[2], utterance_id=old[3]).is_cancelled()
    turn = service.begin_turn(expected_revision=manual[2])
    service.submit("next", defer_until_idle=True, utterance_id="u2")
    service.mark_generation_complete(turn)
    service.finish_turn(turn)
    assert [item[0] for item in delivered] == ["next"]


def test_dequeued_worker_waits_until_history_mutation_completes():
    delivered = []
    service = ChatTurnService(revision_sink=lambda *args: delivered.append(args))
    service.submit("old")
    revision = delivered[0][2]
    attempted = Event()
    finished = Event()
    turns = []

    def begin():
        attempted.set()
        turns.append(service.begin_turn(expected_revision=revision))
        finished.set()

    with service.history_boundary():
        worker = Thread(target=begin)
        worker.start()
        assert attempted.wait(1)
        assert not finished.wait(0.05)
    worker.join(1)
    assert finished.is_set()
    assert turns[0].is_cancelled()


def test_cancelled_turn_cannot_publish_user_history():
    service = ChatTurnService()
    turn = service.begin_turn()
    with service.history_boundary():
        pass
    with service.turn_publication(turn) as current:
        assert not current


@pytest.mark.parametrize("already_delivered", [False, True])
def test_manual_voice_replacement_keeps_absorbed_typed_batch(already_delivered):
    delivered = []
    service = ChatTurnService(
        revision_sink=lambda *args: delivered.append(args),
        options=ChatTurnOptions(batch_enabled=True, batch_idle_seconds=300),
    )
    turn = service.begin_turn()
    try:
        service.submit("typed", interrupt_current=False)
        service.submit("voice", defer_until_idle=True, utterance_id="u1")
        if already_delivered:
            service.mark_generation_complete(turn)
            service.finish_turn(turn)
            old = delivered.pop()
        service.submit("edited", replace_utterance_id="u1", interrupt_current=False)
        service.flush()
        assert [item[0] for item in delivered] == ["typed\n---\nedited"]
        if already_delivered:
            assert service.begin_turn(expected_revision=old[2], utterance_id=old[3]).is_cancelled()
    finally:
        service.close()
