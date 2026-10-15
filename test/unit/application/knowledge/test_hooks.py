from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from application.knowledge.hooks import KnowledgeHooks, install_knowledge_hooks
from config.schema import ApiConfig
from sdk.hooks import BeforeChatContext, PluginHookDispatcher


@pytest.mark.parametrize("configured, expected", [("3", 3), ("0", 1), ("99", 20), ("bad", 5), ("", 5)])
def test_configured_top_k_controls_search_and_injection(monkeypatch, configured, expected):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SEARCH_LIMIT", configured)
    dispatcher = Mock()
    search = Mock(return_value={"memories": [{"memory": f"fact {i}"} for i in range(30)]})
    hooks = install_knowledge_hooks(dispatcher, character_names=["Mika"], search_func=search, status_func=Mock(return_value={"status": "ready"}))
    assert hooks is not None
    dispatcher.register_init_chat.assert_called_once()
    dispatcher.register_init_chat.call_args.args[0](Mock(character_names=("Mika",), knowledge_enabled=True))
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
    monkeypatch.setattr("application.chat.prepare_knowledge.prepare_knowledge", wait)
    hooks = install_knowledge_hooks(dispatcher, search_func=search, status_func=status)
    dispatcher.register_init_chat.assert_called_once()
    dispatcher.register_before_chat.assert_called_once()
    query = BeforeChatContext(messages=[{"role": "user", "content": "fact"}], tools=None, generation_kwargs={}, stream=False)
    hooks.before_chat(query)
    search.assert_not_called()
    context = Mock(character_names=("Mika",), knowledge_enabled=True)
    dispatcher.register_init_chat.call_args.args[0](context)
    wait.assert_called_once_with(context, knowledge_status_func=status)
    assert hooks.enabled is ready
    hooks.before_chat(query)
    assert search.called is ready
