from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from ai.knowledge.hooks import KnowledgeHooks, install_knowledge_hooks
from config.schema import ApiConfig
from sdk.chat_init import ChatInitService, InitChatCancelled, InitChatContext
from sdk.hooks import BeforeChatContext, PluginHookDispatcher


def test_disabled_knowledge_does_not_register_hook(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_ENABLED", "0")
    dispatcher = Mock()
    assert install_knowledge_hooks(dispatcher, character_names=["Mika"]) is None
    dispatcher.register_before_chat.assert_not_called()
    dispatcher.register_init_chat.assert_not_called()


@pytest.mark.parametrize("configured, expected", [("3", 3), ("0", 1), ("99", 20), ("bad", 5), ("", 5)])
def test_configured_top_k_controls_search_and_injection(monkeypatch, configured, expected):
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_ENABLED", raising=False)
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SEARCH_LIMIT", configured)
    dispatcher = Mock()
    hooks = install_knowledge_hooks(dispatcher, character_names=["Mika"])
    assert hooks is not None
    assert dispatcher.register_init_chat.call_args.args[0] == hooks.init_chat
    search = Mock(return_value={"memories": [{"memory": f"fact {i}"} for i in range(30)]})
    hooks.search_func = search
    context = BeforeChatContext(
        messages=[{"role": "user", "content": "library"}],
        tools=None, generation_kwargs={}, stream=False,
    )
    dispatcher.register_before_chat.call_args.args[0](context)
    search.assert_called_once_with("library", character_names=["Mika"], limit=expected)
    assert len(context.messages[-1]["content"].splitlines()) == expected + 1


def test_knowledge_config_preserves_existing_defaults_and_round_trips():
    legacy = ApiConfig()
    assert legacy.knowledge_enabled is True
    assert legacy.knowledge_search_limit == 5
    configured = ApiConfig(knowledge_enabled=False, knowledge_search_limit=7)
    restored = ApiConfig.model_validate_json(configured.model_dump_json())
    assert restored.knowledge_enabled is False
    assert restored.knowledge_search_limit == 7


@pytest.mark.parametrize("limit", [0, 21])
def test_knowledge_config_rejects_out_of_range_top_k(limit):
    with pytest.raises(ValidationError):
        ApiConfig(knowledge_search_limit=limit)


def test_init_starts_loading_once_and_forwards_progress():
    status = Mock(side_effect=[
        {"status": "loading", "task": {
            "phase": "download", "progress": 0.25,
            "message": "Downloading knowledge model", "logs": ["download started"],
        }},
        {"status": "loading", "task": {
            "phase": "reload", "progress": 0.8,
            "logs": ["download started", "model cached"],
        }},
        {"status": "ready"},
    ])
    hooks = KnowledgeHooks(knowledge_status_func=status, sleep_func=lambda _: None)
    dispatcher = PluginHookDispatcher()
    hooks.register(dispatcher)
    events = []
    assert dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService(events.append))) == ()
    assert [call.kwargs for call in status.call_args_list] == [
        {"start_loading": True}, {"start_loading": False}, {"start_loading": False},
    ]
    assert any(event["task"]["message"] == "Downloading knowledge model" for event in events)
    assert any(event["task"]["phase"] == "knowledge.reload" for event in events)
    assert events[-1]["task"]["logs"] == ["download started", "model cached"]
    assert events[-1]["task"]["progress"] == 1.0


@pytest.mark.parametrize("response, expected_error", [
    ({"status": "missing_dependency", "moduleName": "mem0"}, "dependency"),
    ({"status": "error", "message": "load failed"}, "load failed"),
    ({"error": "connection failed"}, "connection failed"),
    ([], "invalid status"),
    ({"status": "unknown"}, "unexpected"),
])
def test_init_failure_does_not_stop_later_hooks(response, expected_error):
    hooks = KnowledgeHooks(knowledge_status_func=Mock(return_value=response))
    dispatcher = PluginHookDispatcher()
    hooks.register(dispatcher)
    continued = Mock()
    dispatcher.register_init_chat(continued, label="after-knowledge")
    failures = dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService()))
    assert len(failures) == 1
    assert failures[0].label == "knowledge"
    assert expected_error in str(failures[0].error)
    continued.assert_called_once()


@pytest.mark.parametrize("response", [None, {"status": "ready"}])
def test_init_unconfigured_or_ready_service_completes(response):
    status = Mock(return_value=response)
    hooks = KnowledgeHooks(knowledge_status_func=status)
    service = ChatInitService()
    hooks.init_chat(InitChatContext(service=service))
    status.assert_called_once_with(start_loading=True)
    assert service.snapshot()["progress"] == 1.0


def test_init_timeout():
    hooks = KnowledgeHooks(
        knowledge_status_func=Mock(return_value={"status": "loading"}),
        init_timeout_seconds=1.0,
        monotonic_func=Mock(side_effect=[0.0, 1.0]),
    )
    with pytest.raises(TimeoutError, match="timed out"):
        hooks.init_chat(InitChatContext(service=ChatInitService()))


def test_init_cancellation_stops_polling_and_later_hooks():
    context = InitChatContext(service=ChatInitService())
    status = Mock(return_value={"status": "loading"})
    hooks = KnowledgeHooks(
        knowledge_status_func=status,
        sleep_func=lambda _: context.cancellation.cancel(),
    )
    dispatcher = PluginHookDispatcher()
    hooks.register(dispatcher)
    continued = Mock()
    dispatcher.register_init_chat(continued, label="after-knowledge")
    with pytest.raises(InitChatCancelled):
        dispatcher.dispatch_init_chat(context)
    status.assert_called_once_with(start_loading=True)
    continued.assert_not_called()
