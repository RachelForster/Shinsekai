from __future__ import annotations

import time

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
    service.submit("two")

    wait_until(lambda: delivered == ["one | two"])
    assert service.batch_state().pending_count == 0


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
