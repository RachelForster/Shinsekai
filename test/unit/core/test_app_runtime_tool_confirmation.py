from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from core.runtime.app_runtime import (
    resolve_pending_tool_confirmation,
    set_app_runtime,
)


def teardown_function():
    set_app_runtime(None)


def test_pending_tool_confirmation_accepts_confirm_option_with_cancel_in_arguments():
    event = Event()
    result: list[bool] = []
    set_app_runtime(
        SimpleNamespace(
            _pending_confirm={"file_write": (event, result)},
        )
    )

    assert resolve_pending_tool_confirmation(
        "⚠️ 确认 file_write\npath=C:\\notes\\cancel-plan.txt"
    )
    assert event.is_set()
    assert result == [True]


def test_pending_tool_confirmation_handles_explicit_cancel():
    event = Event()
    result: list[bool] = []
    set_app_runtime(
        SimpleNamespace(
            _pending_confirm={"file_write": (event, result)},
        )
    )

    assert resolve_pending_tool_confirmation("取消")
    assert event.is_set()
    assert result == [False]


def test_pending_tool_confirmation_returns_false_without_pending_prompt():
    set_app_runtime(SimpleNamespace())

    assert not resolve_pending_tool_confirmation("确认")
