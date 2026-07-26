from __future__ import annotations

from types import SimpleNamespace

from core.runtime.app_runtime import (
    ToolConfirmationController,
    resolve_pending_tool_confirmation,
    set_app_runtime,
)


def teardown_function():
    set_app_runtime(None)


def _runtime_with_controller() -> ToolConfirmationController:
    controller = ToolConfirmationController()
    set_app_runtime(SimpleNamespace(tool_confirmations=controller))
    return controller


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
