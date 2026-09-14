from __future__ import annotations

import time
from threading import Event, Thread

import pytest

from core.messaging.chat_turn_service import BatchState, ChatTurnOptions, ChatTurnService


def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_submit_delivers_immediately_when_batching_is_disabled() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=False),
    )

    service.submit("hello")

    assert delivered == ["hello"]


def test_submit_preserves_attachments_for_immediate_and_batched_delivery() -> None:
    delivered: list[tuple[str, list[dict[str, str]]]] = []
    service = ChatTurnService(
        sink=lambda text, *, attachments: delivered.append((text, attachments)),
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=30,
            batch_separator=" | ",
        ),
    )
    image = {"kind": "image", "name": "scene.png", "path": "C:/scene.png"}
    document = {"kind": "file", "name": "notes.txt", "path": "C:/notes.txt"}

    service.submit("inspect", attachments=[image])
    state = service.submit("", attachments=[document])
    service.flush()

    assert state.pending_messages == ("inspect", "[file: notes.txt]")
    assert delivered == [("inspect", [image, document])]


def test_batched_delivery_preserves_admission_callbacks() -> None:
    admitted: list[tuple[str, list[dict[str, str]]]] = []
    service = ChatTurnService(
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=30,
            batch_separator=" | ",
        ),
    )
    service.submit(
        "one",
        on_admit=lambda text, attachments: admitted.append((text, attachments)),
    )
    service.submit("two")

    service.flush()

    assert admitted == [("one | two", [])]


def test_submit_interrupts_active_turn_before_delivery() -> None:
    events: list[str] = []
    service = ChatTurnService(
        sink=lambda text: events.append(f"send:{text}"),
        options=ChatTurnOptions(interrupt_enabled=True),
        cancel_current=lambda: events.append("cancel"),
        clear_pending=(lambda: events.append("clear"),),
        stop_playback=lambda: events.append("stop"),
    )
    old_turn = service.begin_turn()

    service.submit("next")

    assert old_turn.is_cancelled()
    assert events == ["cancel", "clear", "stop", "send:next"]


def test_interrupt_option_is_honored() -> None:
    cancelled: list[bool] = []
    service = ChatTurnService(
        sink=lambda _text: None,
        options=ChatTurnOptions(interrupt_enabled=False),
        cancel_current=lambda: cancelled.append(True),
    )
    turn = service.begin_turn()

    service.submit("next")

    assert not turn.is_cancelled()
    assert cancelled == []


def test_deferred_submissions_wait_for_complete_turn_and_admit_one_at_a_time() -> None:
    events: list[str] = []
    service = ChatTurnService(
        sink=lambda text: events.append(f"send:{text}"),
        options=ChatTurnOptions(interrupt_enabled=True),
        cancel_current=lambda: events.append("cancel"),
    )
    first_turn = service.begin_turn()

    service.submit("voice one", interrupt_current=False, defer_until_idle=True)
    service.submit("voice two", interrupt_current=False, defer_until_idle=True)

    assert events == []
    assert not first_turn.is_cancelled()
    service.mark_generation_complete(first_turn)
    assert service.finish_turn(first_turn, before_next=lambda: events.append("finished:first"))
    assert events == ["finished:first", "send:voice one"]
    assert service.is_active()
    assert not service.finish_turn(first_turn)

    second_turn = service.begin_turn()
    service.mark_generation_complete(second_turn)
    assert service.finish_turn(second_turn, before_next=lambda: events.append("finished:second"))
    assert events == [
        "finished:first",
        "send:voice one",
        "finished:second",
        "send:voice two",
    ]


def test_deferred_admission_publishes_commit_before_generating_status() -> None:
    events: list[str] = []
    service = ChatTurnService(
        sink=lambda text: events.append(f"send:{text}"),
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    turn = service.begin_turn()
    service.submit(
        "queued voice",
        interrupt_current=False,
        defer_until_idle=True,
        on_admit=lambda text, _attachments: events.extend(
            (f"final:{text}", "status:generating")
        ),
    )

    service.mark_generation_complete(turn)
    service.finish_turn(turn, before_next=lambda: events.append("reply.finished"))

    assert events == [
        "reply.finished",
        "final:queued voice",
        "status:generating",
        "send:queued voice",
    ]


def test_interrupting_submission_during_completion_is_next_priority() -> None:
    events: list[str] = []
    completion_started = Event()
    release_completion = Event()
    service = ChatTurnService(
        sink=lambda text: events.append(f"send:{text}"),
        options=ChatTurnOptions(interrupt_enabled=True),
        cancel_current=lambda: events.append("cancel"),
    )
    first_turn = service.begin_turn()
    service.submit("voice", interrupt_current=False, defer_until_idle=True)
    service.mark_generation_complete(first_turn)

    def finish() -> None:
        service.finish_turn(
            first_turn,
            before_next=lambda: (
                completion_started.set(),
                release_completion.wait(timeout=1),
            ),
        )

    thread = Thread(target=finish)
    thread.start()
    assert completion_started.wait(timeout=1)

    service.submit("manual")
    release_completion.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert events == ["send:manual"]
    second_turn = service.begin_turn()
    service.mark_generation_complete(second_turn)
    service.finish_turn(second_turn)
    assert events == ["send:manual", "send:voice"]


def test_deferred_delivery_failure_releases_admission_reservation() -> None:
    def failing_sink(_text: str) -> None:
        raise RuntimeError("queue closed")

    service = ChatTurnService(
        sink=failing_sink,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    turn = service.begin_turn()
    service.submit("voice", interrupt_current=False, defer_until_idle=True)
    service.mark_generation_complete(turn)

    with pytest.raises(RuntimeError, match="queue closed"):
        service.finish_turn(turn)

    assert not service.is_active()


def test_close_waits_for_inflight_admission_and_rejects_later_delivery() -> None:
    delivery_started = Event()
    release_delivery = Event()
    close_returned = Event()
    delivered: list[str] = []

    def sink(text: str) -> None:
        delivery_started.set()
        release_delivery.wait(timeout=1)
        delivered.append(text)

    service = ChatTurnService(
        sink=sink,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    submit_thread = Thread(
        target=lambda: service.submit(
            "voice",
            interrupt_current=False,
            defer_until_idle=True,
        )
    )
    submit_thread.start()
    assert delivery_started.wait(timeout=1)

    close_thread = Thread(target=lambda: (service.close(), close_returned.set()))
    close_thread.start()
    assert not close_returned.wait(timeout=0.05)
    release_delivery.set()
    submit_thread.join(timeout=1)
    close_thread.join(timeout=1)

    assert close_returned.is_set()
    service.submit("late", interrupt_current=False, defer_until_idle=True)
    service.close()
    assert delivered == ["voice"]


def test_close_clears_buffered_delivery_and_cancels_a_late_worker_turn() -> None:
    queued: list[str] = []
    cleanup_started = Event()
    release_cleanup = Event()

    def clear_buffered_delivery() -> None:
        cleanup_started.set()
        assert release_cleanup.wait(timeout=1)
        queued.clear()

    service = ChatTurnService(
        sink=queued.append,
        clear_buffered_delivery=clear_buffered_delivery,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    service.submit("queued before close", interrupt_current=False)
    assert queued == ["queued before close"]

    close_thread = Thread(target=service.close)
    close_thread.start()
    assert cleanup_started.wait(timeout=1)
    try:
        late_turn = service.begin_turn()
        assert late_turn.is_cancelled()
        assert not service.is_active()
    finally:
        release_cleanup.set()
    close_thread.join(timeout=1)

    assert not close_thread.is_alive()
    assert queued == []


def test_cancel_pending_batch_invalidates_a_dequeued_admission_before_delivery() -> None:
    delivery_paused = Event()
    release_delivery = Event()
    admitted: list[str] = []
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    turn = service.begin_turn()
    service.submit(
        "stale voice",
        interrupt_current=False,
        defer_until_idle=True,
        on_admit=lambda text, _attachments: admitted.append(text),
    )
    original_deliver = service._deliver

    def pause_after_dequeue(admission):
        delivery_paused.set()
        assert release_delivery.wait(timeout=1)
        return original_deliver(admission)

    service._deliver = pause_after_dequeue  # type: ignore[method-assign]
    service.mark_generation_complete(turn)
    finish_thread = Thread(target=lambda: service.finish_turn(turn))
    finish_thread.start()
    assert delivery_paused.wait(timeout=1)

    service.cancel_pending_batch()
    release_delivery.set()
    finish_thread.join(timeout=1)

    assert not finish_thread.is_alive()
    assert admitted == []
    assert delivered == []


def test_finish_turn_does_not_admit_new_branch_input_after_reset_during_completion() -> None:
    completion_started = Event()
    release_completion = Event()
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    old_turn = service.begin_turn()
    service.submit("old branch voice", interrupt_current=False, defer_until_idle=True)
    service.mark_generation_complete(old_turn)

    finish_thread = Thread(
        target=lambda: service.finish_turn(
            old_turn,
            before_next=lambda: (
                completion_started.set(),
                release_completion.wait(timeout=1),
            ),
        )
    )
    finish_thread.start()
    assert completion_started.wait(timeout=1)

    service.cancel_pending_batch()
    new_turn = service.begin_turn()
    service.submit("new branch voice", interrupt_current=False, defer_until_idle=True)
    release_completion.set()
    finish_thread.join(timeout=1)

    assert not finish_thread.is_alive()
    assert delivered == []

    service.mark_generation_complete(new_turn)
    assert service.finish_turn(new_turn)
    assert delivered == ["new branch voice"]


def test_close_before_completion_callback_skips_the_callback() -> None:
    callback_called: list[bool] = []
    guard_checked = Event()
    release_guard = Event()
    service = ChatTurnService(options=ChatTurnOptions(interrupt_enabled=True))
    turn = service.begin_turn()
    service.mark_generation_complete(turn)
    original_guard = service._completion_is_current_locked
    first_guard = True

    def block_first_guard(turn_id: int, revision: int) -> bool:
        nonlocal first_guard
        if first_guard:
            first_guard = False
            guard_checked.set()
            assert release_guard.wait(timeout=1)
        return original_guard(turn_id, revision)

    service._completion_is_current_locked = block_first_guard  # type: ignore[method-assign]
    finish_thread = Thread(
        target=lambda: service.finish_turn(
            turn,
            before_next=lambda: callback_called.append(True),
        )
    )
    finish_thread.start()
    assert guard_checked.wait(timeout=1)

    close_thread = Thread(target=service.close)
    close_thread.start()
    assert service._closed_event.wait(timeout=1)
    release_guard.set()
    finish_thread.join(timeout=1)
    close_thread.join(timeout=1)

    assert not finish_thread.is_alive()
    assert not close_thread.is_alive()
    assert callback_called == []


def test_deferred_final_waits_for_a_queued_manual_turn_before_worker_begin() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=True),
    )

    service.submit("typed", interrupt_current=False)
    service.submit("voice final", interrupt_current=False, defer_until_idle=True)

    assert delivered == ["typed"]
    typed_turn = service.begin_turn()
    service.mark_generation_complete(typed_turn)
    assert service.finish_turn(typed_turn)
    assert delivered == ["typed", "voice final"]


def test_deferred_final_waits_for_a_queued_manual_turn_to_fully_finish() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    first_turn = service.begin_turn()
    service.submit("typed next", interrupt_current=False)
    service.submit("voice final", interrupt_current=False, defer_until_idle=True)

    service.mark_generation_complete(first_turn)
    assert service.finish_turn(first_turn)
    assert delivered == ["typed next"]

    typed_turn = service.begin_turn()
    service.mark_generation_complete(typed_turn)
    assert service.finish_turn(typed_turn)
    assert delivered == ["typed next", "voice final"]


@pytest.mark.parametrize("delivery_path", ("flush", "option_update"))
def test_batched_delivery_waits_for_worker_begin_before_admitting_deferred_final(
    delivery_path: str,
) -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(
            interrupt_enabled=True,
            batch_enabled=True,
            batch_idle_seconds=30,
        ),
    )
    service.submit("typed", interrupt_current=False)

    if delivery_path == "flush":
        service.flush()
    else:
        service.update_options(
            ChatTurnOptions(interrupt_enabled=True, batch_enabled=False)
        )
    service.submit("voice final", interrupt_current=False, defer_until_idle=True)

    assert delivered == ["typed"]
    typed_turn = service.begin_turn()
    service.mark_generation_complete(typed_turn)
    assert service.finish_turn(typed_turn)
    assert delivered == ["typed", "voice final"]


def test_admission_callback_can_reset_without_delivering_a_stale_sink_item() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=True),
    )

    service.submit(
        "stale",
        interrupt_current=False,
        defer_until_idle=True,
        on_admit=lambda _text, _attachments: service.cancel_pending_batch(),
    )

    assert delivered == []
    assert not service.is_active()


def test_batch_flush_does_not_deadlock_with_inflight_direct_delivery() -> None:
    direct_started = Event()
    release_direct = Event()
    delivered: list[str] = []

    def sink(text: str) -> None:
        if text == "direct":
            direct_started.set()
            release_direct.wait(timeout=1)
        delivered.append(text)

    service = ChatTurnService(
        sink=sink,
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=30,
        ),
    )
    direct_thread = Thread(
        target=lambda: service.submit(
            "direct",
            interrupt_current=False,
            defer_until_idle=True,
        )
    )
    direct_thread.start()
    assert direct_started.wait(timeout=1)
    service.submit("batched", interrupt_current=False)
    flush_thread = Thread(target=service.flush)
    flush_thread.start()

    release_direct.set()
    direct_thread.join(timeout=1)
    flush_thread.join(timeout=1)

    assert not direct_thread.is_alive()
    assert not flush_thread.is_alive()
    assert delivered == ["direct", "batched"]


def test_cancel_pending_batch_discards_deferred_submissions() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(interrupt_enabled=True),
    )
    turn = service.begin_turn()
    service.submit("stale voice", interrupt_current=False, defer_until_idle=True)

    service.cancel_pending_batch()
    service.mark_generation_complete(turn)
    service.finish_turn(turn)

    assert delivered == []


def test_interrupting_input_is_admitted_before_earlier_deferred_voice() -> None:
    events: list[str] = []
    service = ChatTurnService(
        sink=lambda text: events.append(f"send:{text}"),
        options=ChatTurnOptions(interrupt_enabled=True),
        cancel_current=lambda: events.append("cancel"),
    )
    interrupted_turn = service.begin_turn()
    service.submit("deferred voice", interrupt_current=False, defer_until_idle=True)

    service.submit("manual interrupt")

    assert interrupted_turn.is_cancelled()
    assert events == ["cancel", "send:manual interrupt"]
    manual_turn = service.begin_turn()
    service.mark_generation_complete(manual_turn)
    service.finish_turn(manual_turn)
    assert events == ["cancel", "send:manual interrupt", "send:deferred voice"]


def test_deferred_voice_flushes_existing_batch_as_one_deferred_turn() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(
            interrupt_enabled=True,
            batch_enabled=True,
            batch_idle_seconds=30,
            batch_separator=" | ",
        ),
    )
    turn = service.begin_turn()
    service.submit("typed fragment", interrupt_current=False)

    state = service.submit(
        "voice final",
        interrupt_current=False,
        defer_until_idle=True,
    )

    assert state.pending_count == 0
    assert delivered == []
    service.mark_generation_complete(turn)
    service.finish_turn(turn)
    assert delivered == ["typed fragment | voice final"]


def test_batch_auto_flushes_without_a_ui_timer() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=0.03,
            batch_separator=" | ",
        ),
    )

    service.submit("one")
    pending = service.submit("two")

    assert pending.pending_messages == ("one", "two")
    wait_until(lambda: delivered == ["one | two"])
    flushed = service.batch_state()
    assert flushed.pending_count == 0
    assert flushed.pending_messages == ()


def test_typing_pauses_and_empty_input_reschedules_batch() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=0.04,
        ),
    )

    service.submit("one")
    paused = service.input_changed(has_text=True)
    time.sleep(0.06)

    assert paused.typing
    assert delivered == []

    scheduled = service.input_changed(has_text=False)
    assert scheduled.scheduled
    wait_until(lambda: delivered == ["one"])


def test_cancel_pending_batch_invalidates_timer_and_clears_buffered_delivery() -> None:
    delivered: list[str] = ["already queued"]
    service = ChatTurnService(
        sink=delivered.append,
        clear_buffered_delivery=delivered.clear,
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=0.03,
        ),
    )
    service.submit("stale branch input")

    state = service.cancel_pending_batch()
    time.sleep(0.06)

    assert delivered == []
    assert state.pending_count == 0
    assert not state.scheduled


def test_turn_handles_keep_old_work_cancelled_after_new_turn_starts() -> None:
    service = ChatTurnService(options=ChatTurnOptions(interrupt_enabled=True))
    first = service.begin_turn()

    service.interrupt()
    second = service.begin_turn()

    assert first.is_cancelled()
    assert not second.is_cancelled()
    assert first.id != second.id


def test_pipeline_stays_active_until_generation_and_downstream_are_idle() -> None:
    service = ChatTurnService(options=ChatTurnOptions(interrupt_enabled=True))
    turn = service.begin_turn()

    service.mark_idle(turn)
    assert service.is_active()

    service.mark_generation_complete(turn)
    service.mark_idle(turn)
    assert not service.is_active()


def test_option_update_flushes_pending_batch_when_batching_is_disabled() -> None:
    delivered: list[str] = []
    states: list[BatchState] = []
    service = ChatTurnService(
        sink=delivered.append,
        on_state_change=states.append,
        options=ChatTurnOptions(
            interrupt_enabled=True,
            batch_enabled=True,
            batch_idle_seconds=30,
            batch_separator=" | ",
        ),
    )
    service.submit("one")
    service.submit("two")

    state = service.update_options(
        ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=False,
            batch_idle_seconds=5,
            batch_separator="\n---\n",
        )
    )

    assert delivered == ["one | two"]
    assert not state.enabled
    assert state.pending_count == 0
    assert states[-1] == state


def test_option_update_reschedules_pending_batch_with_new_timeout() -> None:
    delivered: list[str] = []
    service = ChatTurnService(
        sink=delivered.append,
        options=ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=30,
        ),
    )
    service.submit("one")

    state = service.update_options(
        ChatTurnOptions(
            interrupt_enabled=False,
            batch_enabled=True,
            batch_idle_seconds=0.03,
        )
    )

    assert state.scheduled
    wait_until(lambda: delivered == ["one"])
