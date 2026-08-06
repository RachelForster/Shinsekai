from __future__ import annotations

import pytest

import sdk.runtime_errors as runtime_errors
from sdk.chat_ui_context import (
    ChatUIContext,
    get_chat_ui_context,
    set_chat_ui_context,
    try_get_chat_ui_context,
)


def test_retired_chat_ui_context_fails_with_an_actionable_replacement():
    marker = object()
    set_chat_ui_context(None)
    try:
        assert try_get_chat_ui_context() is None
        with pytest.raises(RuntimeError, match=r"register\.frontend_ui"):
            get_chat_ui_context()
        with pytest.raises(RuntimeError, match=r"register\.frontend_ui"):
            ChatUIContext.bind(marker, enabled=True)

        set_chat_ui_context(marker)
        assert try_get_chat_ui_context() is marker
        assert get_chat_ui_context() is marker
    finally:
        set_chat_ui_context(None)


def test_runtime_error_compatibility_surface_exports_the_canonical_api():
    assert runtime_errors.RuntimeDependencyError.__module__ == "sdk.exception.types"
    assert runtime_errors.show_error_dialog.__module__ == "sdk.exception.handler"
    assert set(runtime_errors.__all__) >= {
        "RuntimeDependencyError",
        "runtime_dependency_error_from_exception",
        "show_error_dialog",
    }
