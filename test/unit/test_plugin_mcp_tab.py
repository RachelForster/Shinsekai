from __future__ import annotations

import pytest

from ui.settings_ui.tabs.plugin_mcp_tab import _McpServerEditDialog


pytestmark = pytest.mark.unit


def test_mcp_server_dialog_stdio_default_selects_stdio(qtbot) -> None:
    dlg = _McpServerEditDialog(None, "stdio")
    qtbot.addWidget(dlg)

    assert dlg._transport.currentData() == "stdio"


def test_mcp_server_dialog_rejects_blocked_stdio_command(qtbot) -> None:
    dlg = _McpServerEditDialog(None, "stdio")
    qtbot.addWidget(dlg)
    dlg._command.setText("bash")
    dlg._args_json.setPlainText('["-lc", "echo owned"]')

    with pytest.raises(ValueError, match="not allowed"):
        dlg._validated_result()
