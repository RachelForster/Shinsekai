from __future__ import annotations

import pytest

from sdk.chat_init import (
    ChatInitService,
    InitChatCancellationToken,
    InitChatCancelled,
    InitChatContext,
)


def test_chat_init_service_emits_monotonic_task_progress_and_completion() -> None:
    events: list[dict] = []
    service = ChatInitService(events.append, task_id="chat-init-test")

    service.start("Preparing")
    service.phase_started("tts", "Starting TTS", progress=0.2)
    service.report(progress=0.75, message="TTS server is responding")
    regressed = service.report(progress=0.3, message="Late progress callback")
    completed = service.completed("Ready", result={"sessionId": "session-1"})

    assert regressed["progress"] == 0.75
    assert completed["id"] == "chat-init-test"
    assert completed["kind"] == "chat-initialization"
    assert completed["message"] == "Ready"
    assert completed["phase"] == "completed"
    assert completed["progress"] == 1.0
    assert completed["result"] == {"sessionId": "session-1"}
    assert completed["status"] == "succeeded"
    assert [event["type"] for event in events] == [
        "chat.init.progress",
        "chat.init.progress",
        "chat.init.progress",
        "chat.init.progress",
        "chat.init.completed",
    ]
    assert all(event.keys() == {"type", "task"} for event in events)
    assert [event["task"]["progress"] for event in events] == [0.0, 0.2, 0.75, 0.75, 1.0]


def test_init_chat_context_scales_progress_and_honors_cancellation() -> None:
    events: list[dict] = []
    token = InitChatCancellationToken()
    context = InitChatContext(
        service=ChatInitService(events.append),
        cancellation=token,
    ).scaled(0.2, 0.6)

    context.phase_started("plugin", "Starting plugin")
    context.report(0.5, "Halfway")
    context.phase_completed("plugin", "Plugin ready")

    assert [event["task"]["progress"] for event in events] == pytest.approx([0.2, 0.4, 0.6])

    token.cancel("user cancelled")
    with pytest.raises(InitChatCancelled, match="user cancelled"):
        context.report(1.0)


@pytest.mark.parametrize(
    ("terminal_method", "event_type", "status"),
    [
        ("failed", "chat.init.failed", "failed"),
        ("cancelled", "chat.init.cancelled", "cancelled"),
    ],
)
def test_chat_init_service_emits_terminal_failure_states(
    terminal_method: str,
    event_type: str,
    status: str,
) -> None:
    events: list[dict] = []
    service = ChatInitService(events.append)
    service.start()

    if terminal_method == "failed":
        task = service.failed(RuntimeError("boom"))
        assert task["error"] == "boom"
    else:
        task = service.cancelled("stop")

    assert task["status"] == status
    assert events[-1] == {"type": event_type, "task": task}

    event_count = len(events)
    service.report(progress=1.0, message="ignored after terminal")
    assert len(events) == event_count
