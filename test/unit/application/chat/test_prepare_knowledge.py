from unittest.mock import Mock

import pytest

from application.chat.prepare_knowledge import prepare_knowledge
from application.knowledge.hooks import KnowledgeHooks
from sdk.chat_init import InitChatCancelled, InitChatContext, ChatInitService
from sdk.hooks import BeforeChatContext


def test_starts_loading_once_and_forwards_incremental_progress():
    status = Mock(side_effect=[
        {"status": "loading", "task": {"phase": "download", "progress": 0.25,
            "message": "Downloading knowledge model", "logs": ["download started"]}},
        {"status": "loading", "task": {"phase": "reload", "progress": 0.8,
            "logs": ["download started", "model cached"]}},
        {"status": "ready"},
    ])
    events = []
    context = InitChatContext(service=ChatInitService(events.append))
    assert prepare_knowledge(context, knowledge_status_func=status, sleep_func=lambda _: None)
    assert [call.kwargs for call in status.call_args_list] == [
        {"start_loading": True}, {"start_loading": False}, {"start_loading": False},
    ]
    assert any(event["task"]["phase"] == "knowledge.reload" for event in events)
    assert events[-1]["task"]["logs"] == ["download started", "model cached"]
    assert events[-1]["task"]["progress"] == 1.0


@pytest.mark.parametrize("response, reason", [
    ({"status": "missing_dependency", "moduleName": "mem0"}, "dependency"),
    ({"status": "error", "message": "load failed"}, "load failed"),
    ({"error": "connection failed"}, "connection failed"),
    ([], "invalid status"),
    ({"status": "unknown"}, "unexpected"),
])
def test_failure_degrades_and_preserves_reason(response, reason):
    service = ChatInitService()
    assert not prepare_knowledge(
        InitChatContext(service=service), knowledge_status_func=Mock(return_value=response),
    )
    snapshot = service.snapshot()
    assert snapshot["phase"] == "knowledge.degraded"
    assert reason in snapshot["logs"][-1]
    assert snapshot["status"] != "failed"


@pytest.mark.parametrize("response, ready", [(None, False), ({"status": "ready"}, True)])
def test_unconfigured_or_ready_service_completes(response, ready):
    status = Mock(return_value=response)
    service = ChatInitService()
    assert prepare_knowledge(InitChatContext(service=service), knowledge_status_func=status) is ready
    status.assert_called_once_with(start_loading=True)
    assert service.snapshot()["progress"] == 1.0


def test_timeout_degrades():
    service = ChatInitService()
    assert not prepare_knowledge(
        InitChatContext(service=service), knowledge_status_func=Mock(return_value={"status": "loading"}),
        timeout=1.0, monotonic_func=Mock(side_effect=[0.0, 1.0]),
    )
    assert "timed out" in service.snapshot()["logs"][-1]


def test_cancellation_stops_polling():
    context = InitChatContext(service=ChatInitService())
    status = Mock(return_value={"status": "loading"})
    with pytest.raises(InitChatCancelled):
        prepare_knowledge(context, knowledge_status_func=status,
                          sleep_func=lambda _: context.cancellation.cancel())
    status.assert_called_once_with(start_loading=True)


def test_cancellation_during_failed_request_is_not_degraded():
    context = InitChatContext(service=ChatInitService())

    def status(**kwargs):
        context.cancellation.cancel()
        raise RuntimeError("connection closed")

    with pytest.raises(InitChatCancelled):
        prepare_knowledge(context, knowledge_status_func=status)
    assert context.service.snapshot()["phase"] != "knowledge.degraded"


def test_degraded_hook_does_not_search_on_first_message():
    search = Mock()
    hooks = KnowledgeHooks(character_names=["A"], search_func=search)
    hooks.enabled = False
    context = BeforeChatContext(messages=[{"role": "user", "content": "hello"}],
                                tools=None, generation_kwargs={}, stream=False)
    hooks.before_chat(context)
    search.assert_not_called()


def test_connection_exception_degrades():
    service = ChatInitService()
    assert not prepare_knowledge(
        InitChatContext(service=service), knowledge_status_func=Mock(side_effect=OSError("offline")),
    )
    assert "offline" in service.snapshot()["logs"][-1]
