"""Continuous input shares stacked timing, without crossing reply boundaries."""

from dataclasses import replace
from threading import Event, Thread

import pytest

from core.messaging.continuous_asr_policy import ContinuousASRPolicy
from core.messaging.chat_turn_service import ChatTurnOptions, ChatTurnService


def test_policy_tracks_opaque_batches_without_access_to_service_or_payload():
    policy = ContinuousASRPolicy()
    first, second = object(), object()
    policy.track(first, identity="batch:1", sources=("a", "b"))
    policy.track(second, identity="batch:2", sources=("c",))
    policy.defer(first)
    policy.defer(second)

    assert policy.retire("a") is first
    assert policy.is_retired("a") and policy.is_retired("batch:1")
    assert not policy.is_retired("b")
    assert policy.pop() is second
    assert policy.pop() is None
    policy.begin_turn("batch:2")
    assert policy.retire("c") is None
    policy.invalidate()
    assert not policy.is_retired("a")
    assert not policy.is_retired("batch:1")


def test_rejected_empty_replacement_preserves_the_waiting_speech():
    delivered = []
    service = ChatTurnService(continuous_policy=ContinuousASRPolicy(), sink=delivered.append)
    try:
        turn = service.begin_turn()
        service.submit("keep", defer_until_idle=True, utterance_id="u1")
        service.submit("", replace_utterance_id="u1")
        service.mark_generation_complete(turn)
        service.finish_turn(turn)
        assert delivered == ["keep"]
    finally:
        service.close()


@pytest.fixture
def batch_service():
    delivered = []
    service = ChatTurnService(continuous_policy=ContinuousASRPolicy(),
        revision_sink=lambda *args: delivered.append(args),
        options=ChatTurnOptions(batch_enabled=True, batch_idle_seconds=300, batch_separator=" | "),
    )
    yield service, delivered
    service.close()



def expire_timer(service):
    timer = service._batch_timer
    assert timer is not None
    timer.function(*timer.args, **timer.kwargs)



@pytest.mark.parametrize("reply_first", [False, True])
def test_batch_needs_both_idle_timeout_and_full_reply_completion(batch_service, reply_first):
    service, delivered = batch_service
    callbacks = []
    turn = service.begin_turn()
    for i, text in enumerate(("first", "second")):
        service.submit(text, defer_until_idle=True, utterance_id=str(i),
                       on_admit=lambda text, _attachments: callbacks.append(text))
    service.mark_generation_complete(turn)
    assert not turn.is_cancelled()
    assert not delivered and not callbacks
    if reply_first:
        service.finish_turn(turn)
        assert not delivered
        expire_timer(service)
    else:
        expire_timer(service)
        assert not delivered
        service.finish_turn(turn)
    assert [item[0] for item in delivered] == ["first | second"]
    assert callbacks == ["first | second", "first | second"]



def test_each_final_resets_official_timer_and_expired_batches_stay_separate(batch_service):
    service, delivered = batch_service
    turn = service.begin_turn()
    service.submit("one", defer_until_idle=True)
    obsolete = service._batch_timer
    service.submit("two", defer_until_idle=True)
    obsolete.function(*obsolete.args, **obsolete.kwargs)
    assert service.batch_state().pending_messages == ("one", "two")
    expire_timer(service)
    service.submit("three", defer_until_idle=True)
    expire_timer(service)
    service.mark_generation_complete(turn)
    service.finish_turn(turn)
    assert [item[0] for item in delivered] == ["one | two"]
    second = service.begin_turn()
    service.mark_generation_complete(second)
    service.finish_turn(second)
    assert [item[0] for item in delivered] == ["one | two", "three"]



@pytest.mark.parametrize("flush", ["manual", "disable_stacked"])
def test_explicit_flush_still_waits_for_full_reply(batch_service, flush):
    service, delivered = batch_service
    turn = service.begin_turn()
    service.submit("voice", defer_until_idle=True)
    if flush == "manual":
        service.flush()
    else:
        service.update_options(replace(service.options, batch_enabled=False))
    assert not delivered and not turn.is_cancelled()
    service.mark_generation_complete(turn)
    service.finish_turn(turn)
    assert [item[0] for item in delivered] == ["voice"]



def test_manual_draft_and_speech_activity_are_independent(batch_service):
    service, delivered = batch_service
    service.submit("one", defer_until_idle=True)
    service.input_changed(has_text=True, source="asr")
    assert not service.batch_state().scheduled
    service.input_changed(has_text=True)
    service.submit("two", defer_until_idle=True)
    assert service.batch_state().typing
    assert not service.batch_state().scheduled
    service.input_changed(has_text=False)
    expire_timer(service)
    assert [item[0] for item in delivered] == ["one | two"]



@pytest.mark.parametrize("stage", ["batch", "deferred", "queued"])
def test_edit_keeps_other_sources_and_attachments_without_duplicate_turn(batch_service, stage):
    service, delivered = batch_service
    first = service.begin_turn()
    callbacks = []
    image = {"kind": "image", "path": "image.png"}
    service.submit("typed", attachments=[image], interrupt_current=False)
    service.submit("keep", defer_until_idle=True, utterance_id="u1",
                   on_admit=lambda *_: callbacks.append("u1"))
    service.submit("replace", defer_until_idle=True, utterance_id="u2",
                   on_admit=lambda *_: callbacks.append("u2"))
    if stage != "batch":
        expire_timer(service)
    if stage == "queued":
        service.mark_generation_complete(first)
        service.finish_turn(first)
        old = delivered.pop()
        callbacks.clear()
    service.input_changed(has_text=True)
    service.submit("edited", replace_utterance_id="u2", interrupt_current=False)
    expire_timer(service)
    if stage == "queued":
        assert service.begin_turn(expected_revision=old[2], utterance_id=old[3]).is_cancelled()
    else:
        service.mark_generation_complete(first)
        service.finish_turn(first)
    assert [(item[0], item[1]) for item in delivered] == [("typed | keep | edited", [image])]
    assert callbacks == ["u1"]
    latest = delivered[0]
    turn = service.begin_turn(expected_revision=latest[2], utterance_id=latest[3])
    assert not turn.is_cancelled()
    service.mark_generation_complete(turn)
    service.finish_turn(turn)
    assert len(delivered) == 1



@pytest.mark.parametrize("boundary", ["reset", "history", "close"])
def test_boundary_revokes_popped_batch_before_callbacks_or_sink(batch_service, boundary):
    service, delivered = batch_service
    turn = service.begin_turn()
    callbacks = []
    service.submit("one", defer_until_idle=True, utterance_id="u1", on_admit=lambda *_: callbacks.append(1))
    service.submit("two", defer_until_idle=True, utterance_id="u2")
    expire_timer(service)
    service.mark_generation_complete(turn)
    popped, release = Event(), Event()
    deliver = service._deliver

    def blocked(admission):
        popped.set()
        assert release.wait(2)
        return deliver(admission)

    service._deliver = blocked
    worker = Thread(target=lambda: service.finish_turn(turn))
    worker.start()
    assert popped.wait(2)
    if boundary == "history":
        with service.history_boundary():
            pass
    elif boundary == "close":
        service.close()
    else:
        service.cancel_pending_batch()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert not delivered and not callbacks



def test_interrupted_turn_does_not_strand_a_mixed_batch(batch_service):
    service, delivered = batch_service
    turn = service.begin_turn()
    service.submit("typed first")
    service.submit("typed second")
    service.submit("voice", defer_until_idle=True, utterance_id="u1")
    assert turn.is_cancelled()
    expire_timer(service)
    assert [item[0] for item in delivered] == ["typed first | typed second | voice"]
    next_turn = service.begin_turn()
    service.mark_generation_complete(next_turn)
    service.finish_turn(next_turn)
    assert not service.is_active()
    assert len(delivered) == 1



def test_flush_waits_for_interrupt_cleanup(batch_service):
    service, delivered = batch_service
    entered, release, flushed = Event(), Event(), Event()

    def cleanup():
        entered.set()
        assert release.wait(2)

    service._cancel_current = cleanup
    service.begin_turn()
    submitter = Thread(target=lambda: service.submit("typed"))
    submitter.start()
    assert entered.wait(2)
    flusher = Thread(target=lambda: (expire_timer(service), flushed.set()))
    flusher.start()
    try:
        assert not flushed.wait(0.05)
        assert not delivered
    finally:
        release.set()
        submitter.join(2)
        flusher.join(2)
    assert not submitter.is_alive() and not flusher.is_alive()
    assert [item[0] for item in delivered] == ["typed"]



def test_retired_popped_admission_does_not_starve_next_sealed_batch(batch_service):
    service, delivered = batch_service
    turn = service.begin_turn()
    service.submit("old", defer_until_idle=True, utterance_id="old")
    expire_timer(service)
    service.submit("next", defer_until_idle=True, utterance_id="next")
    expire_timer(service)
    service.mark_generation_complete(turn)
    popped, release = Event(), Event()
    deliver = service._deliver

    def blocked(admission):
        if admission.utterance_id == "old":
            popped.set()
            assert release.wait(2)
        return deliver(admission)

    service._deliver = blocked
    worker = Thread(target=lambda: service.finish_turn(turn))
    worker.start()
    try:
        assert popped.wait(2)
        service.submit("edited", replace_utterance_id="old", interrupt_current=False)
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert [item[0] for item in delivered] == ["next"]
    assert service.batch_state().pending_messages == ("edited",)



def test_legacy_sink_releases_source_tracking_when_worker_begins():
    service = ChatTurnService(continuous_policy=ContinuousASRPolicy(), sink=lambda text: None)
    try:
        service.submit("voice", defer_until_idle=True, utterance_id="u1")
        service.begin_turn()
        assert service.continuous_policy.retire("u1") is None
    finally:
        service.close()



def test_rejected_old_delivery_keeps_newer_admission_reservation(batch_service):
    service, delivered = batch_service
    old_popped, new_popped, release_old, release_new = Event(), Event(), Event(), Event()
    deliver = service._deliver

    def blocked(admission):
        if admission.utterance_id == "old":
            old_popped.set()
            assert release_old.wait(2)
        elif admission.text == "edited | new":
            new_popped.set()
            assert release_new.wait(2)
        return deliver(admission)

    service._deliver = blocked
    turn = service.begin_turn()
    service.submit("old", defer_until_idle=True, utterance_id="old")
    expire_timer(service)
    service.mark_generation_complete(turn)
    finisher = Thread(target=lambda: service.finish_turn(turn))
    replacement = Thread(target=lambda: expire_timer(service))
    try:
        finisher.start()
        assert old_popped.wait(2)
        service.submit("edited", replace_utterance_id="old", interrupt_current=False)
        service.submit("new", defer_until_idle=True, utterance_id="new")
        replacement.start()
        assert new_popped.wait(2)
        release_old.set()
        finisher.join(2)
        assert not finisher.is_alive()
        # New delivery is reserved but has not reached the sink. Rejection of
        # the old input must not let a subsequent sealed batch overtake it.
        service.submit("third", defer_until_idle=True)
        expire_timer(service)
        assert not delivered
        release_new.set()
        replacement.join(2)
        finisher.join(2)
        assert not replacement.is_alive() and not finisher.is_alive()
        assert [item[0] for item in delivered] == ["edited | new"]
        next_turn = service.begin_turn()
        service.mark_generation_complete(next_turn)
        service.finish_turn(next_turn)
        assert [item[0] for item in delivered] == ["edited | new", "third"]
    finally:
        release_old.set()
        release_new.set()
        finisher.join(2)
        if replacement.ident is not None:
            replacement.join(2)
        service.close()
