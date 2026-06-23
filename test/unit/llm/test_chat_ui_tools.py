from types import SimpleNamespace

from core.runtime.app_runtime import set_app_runtime
from llm.tools.chat_ui_tools import _tool_set_user_display_name, sanitize_user_display_name


class _Ui:
    def __init__(self):
        self.names = []

    def set_user_display_name(self, name: str) -> None:
        self.names.append(name)


def teardown_function():
    set_app_runtime(None)


def test_set_user_display_name_tool_updates_runtime_ui():
    ui = _Ui()
    set_app_runtime(SimpleNamespace(ui_update_manager=ui))

    result = _tool_set_user_display_name("  「澪」  ")

    assert result == {"ok": True, "userDisplayName": "澪"}
    assert ui.names == ["澪"]


def test_sanitize_user_display_name_rejects_default_and_unsafe_values():
    assert sanitize_user_display_name("你") == ""
    assert sanitize_user_display_name("<b>澪</b>") == "澪"
    assert sanitize_user_display_name("bad<name") == ""
