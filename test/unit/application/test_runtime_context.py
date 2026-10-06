from __future__ import annotations

from types import SimpleNamespace

import pytest

from application.runtime.context import (
    _ApplicationLLMHostRuntime,
    ToolConfirmationController,
    app_runtime_scope,
    get_app_runtime,
    resolve_pending_tool_confirmation,
    set_app_runtime,
    try_get_app_runtime,
)
from sdk.agent import AgentDelegationRequest, AgentRequestError, NullAgentRequester


def teardown_function():
    set_app_runtime(None)


def _runtime_with_controller() -> ToolConfirmationController:
    controller = ToolConfirmationController()
    set_app_runtime(SimpleNamespace(tool_confirmations=controller))
    return controller


def test_runtime_scope_restores_the_previous_context_after_dispatch_errors():
    shared = SimpleNamespace(presentation_queue="shared")
    outer = SimpleNamespace(presentation_queue="outer")
    inner = SimpleNamespace(presentation_queue="inner")
    set_app_runtime(shared)

    with app_runtime_scope(outer):
        assert get_app_runtime() is outer
        with pytest.raises(RuntimeError, match="dispatch failed"):
            with app_runtime_scope(inner):
                assert try_get_app_runtime() is inner
                raise RuntimeError("dispatch failed")
        assert get_app_runtime() is outer

    assert get_app_runtime() is shared
    set_app_runtime(None)
    assert try_get_app_runtime() is None


def test_tool_confirmation_requires_the_matching_unpredictable_identifier():
    controller = _runtime_with_controller()
    prompt = controller.create("file_write")

    assert not resolve_pending_tool_confirmation("wrong-id", "confirm")
    assert not prompt.event.is_set()
    assert prompt.confirmed is None

    assert resolve_pending_tool_confirmation(prompt.confirmation_id, "confirm")
    assert prompt.event.is_set()
    assert prompt.confirmed is True


def test_tool_confirmation_cancel_is_structured_and_one_time():
    controller = _runtime_with_controller()
    prompt = controller.create("file_write")

    assert resolve_pending_tool_confirmation(prompt.confirmation_id, "cancel")
    assert prompt.event.is_set()
    assert prompt.confirmed is False
    assert not resolve_pending_tool_confirmation(prompt.confirmation_id, "confirm")


def test_tool_confirmation_rejects_arbitrary_option_labels():
    controller = _runtime_with_controller()
    prompt = controller.create("file_write")

    assert not resolve_pending_tool_confirmation(prompt.confirmation_id, "取消")
    assert not resolve_pending_tool_confirmation(prompt.confirmation_id, "cancel-plan.txt")
    assert not prompt.event.is_set()


def test_tool_confirmation_identifiers_are_unique():
    controller = _runtime_with_controller()

    first = controller.create("file_write")
    second = controller.create("file_write")

    assert first.confirmation_id != second.confirmation_id
    assert len(first.confirmation_id) >= 24


def test_agent_requester_follows_the_scoped_chat_runtime():
    host = _ApplicationLLMHostRuntime()
    shared_requester = NullAgentRequester()
    scoped_requester = NullAgentRequester()
    set_app_runtime(SimpleNamespace(agent_requester=shared_requester))

    assert host.get_agent_requester() is shared_requester
    with app_runtime_scope(SimpleNamespace(agent_requester=scoped_requester)):
        assert host.get_agent_requester() is scoped_requester
    assert host.get_agent_requester() is shared_requester


@pytest.mark.parametrize("runtime", [None, SimpleNamespace()])
def test_agent_requester_without_a_bound_runtime_is_explicitly_unavailable(runtime):
    set_app_runtime(runtime)
    host = _ApplicationLLMHostRuntime()
    with pytest.raises(AgentRequestError) as failure:
        host.get_agent_requester().request_agent(AgentDelegationRequest(task="inspect"))
    assert failure.value.error.code == "BACKEND_UNAVAILABLE"
