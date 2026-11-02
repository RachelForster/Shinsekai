from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from application.knowledge.hooks import KnowledgeHooks, install_knowledge_hooks
from config.schema import ApiConfig
from sdk.chat_init import ChatInitService, InitChatContext
from sdk.hooks import BeforeChatContext, PluginHookDispatcher


@pytest.mark.parametrize("configured, expected", [("3", 3), ("0", 1), ("99", 20), ("bad", 5), ("", 5)])
def test_configured_top_k_controls_search_and_injection(monkeypatch, configured, expected):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SEARCH_LIMIT", configured)
    dispatcher = Mock()
    search = Mock(return_value={"memories": [{"memory": f"fact {i}"} for i in range(30)]})
    hooks = install_knowledge_hooks(dispatcher, character_names=["Mika"], search_func=search, status_func=Mock(return_value={"status": "ready"}))
    assert hooks is not None
    dispatcher.register_init_chat.assert_called_once()
    dispatcher.register_init_chat.call_args.args[0](InitChatContext(service=ChatInitService(), character_names=("Mika",)))
    context = BeforeChatContext(
        messages=[{"role": "user", "content": "library"}],
        tools=None, generation_kwargs={}, stream=False,
    )
    dispatcher.register_before_chat.call_args.args[0](context)
    search.assert_called_once_with("library", character_names=["Mika"], limit=expected)
    assert len(context.messages[-1]["content"].splitlines()) == expected + 1


def test_knowledge_config_defaults_to_disabled_and_round_trips():
    legacy = ApiConfig()
    assert legacy.knowledge_enabled is False
    assert legacy.knowledge_search_limit == 5
    configured = ApiConfig(knowledge_enabled=True, knowledge_search_limit=7)
    restored = ApiConfig.model_validate_json(configured.model_dump_json())
    assert restored.knowledge_enabled is True
    assert restored.knowledge_search_limit == 7


@pytest.mark.parametrize("limit", [0, 21])
def test_knowledge_config_rejects_out_of_range_top_k(limit):
    with pytest.raises(ValidationError):
        ApiConfig(knowledge_search_limit=limit)


@pytest.mark.parametrize("ready", [True, False])
def test_registered_search_runs_only_after_remote_ready(monkeypatch, ready):
    dispatcher = Mock()
    search = Mock(return_value={"memories": []})
    status = Mock()
    wait = Mock(return_value=ready)
    monkeypatch.setattr("application.knowledge.hooks.prepare_knowledge", wait)
    hooks = install_knowledge_hooks(dispatcher, search_func=search, status_func=status)
    dispatcher.register_init_chat.assert_called_once()
    dispatcher.register_before_chat.assert_called_once()
    query = BeforeChatContext(messages=[{"role": "user", "content": "fact"}], tools=None, generation_kwargs={}, stream=False)
    hooks.before_chat(query)
    search.assert_not_called()
    context = InitChatContext(service=ChatInitService(), character_names=("Mika",))
    dispatcher.register_init_chat.call_args.args[0](context)
    wait.assert_called_once_with(context, knowledge_status_func=status)
    assert hooks.enabled is ready
    hooks.before_chat(query)
    assert search.called is ready


@pytest.mark.parametrize("character_names", [(), ("Mika",)])
def test_initialization_uses_generic_context_and_skips_unused_retrieval(character_names):
    status = Mock(return_value={"status": "ready"})
    hooks = KnowledgeHooks(status_func=status)

    hooks.init_chat(InitChatContext(service=ChatInitService(), character_names=character_names))

    assert hooks.character_names == list(character_names)
    assert hooks.enabled is bool(character_names)
    if character_names:
        status.assert_called_once_with(start_loading=True)
    else:
        status.assert_not_called()


@pytest.mark.parametrize("prefix", ["[本地时间 2026-10-17 10:20:30]\n", "[Local time 2026-10-17 10:20:30]\n", ""])
@pytest.mark.parametrize("text", ["library", ""])
def test_search_uses_user_text_without_chat_time_prefix(prefix, text):
    search = Mock(return_value={"memories": []})
    hooks = KnowledgeHooks(character_names=["Mika"], search_func=search)
    hooks.enabled = True
    context = BeforeChatContext(
        messages=[{"role": "user", "content": prefix + text}],
        tools=None, generation_kwargs={}, stream=False,
    )

    hooks.before_chat(context)

    if text:
        search.assert_called_once_with(text, character_names=["Mika"], limit=5)
    else:
        search.assert_not_called()


@pytest.mark.parametrize("stream", [False, True])
def test_retrieved_knowledge_reaches_llm_without_entering_history(mock_llm_adapter, stream):
    from ai.llm.llm_manager import LLMManager

    dispatcher = PluginHookDispatcher()
    search = Mock(return_value={"memories": [{"memory": "The library closes at six."}]})
    install_knowledge_hooks(
        dispatcher, search_func=search, status_func=Mock(return_value={"status": "ready"}),
    )
    dispatcher.dispatch_init_chat(InitChatContext(service=ChatInitService(), character_names=("Mika",)))
    manager = LLMManager(adapter=mock_llm_adapter, user_template="S", hook_dispatcher=dispatcher)

    for question in ("library", "opening hours"):
        response = manager.chat(question, stream=stream)
        if stream:
            list(response)
        assert search.call_args.args == (question,)
        request = mock_llm_adapter.call_history[-1]["messages"]
        assert request[-1]["role"] == "system"
        assert "The library closes at six." in request[-1]["content"]
        assert sum(message["role"] == "system" for message in request) == 2
        assert [message for message in manager.messages if message["role"] == "system"] == [
            {"role": "system", "content": "S"},
        ]
