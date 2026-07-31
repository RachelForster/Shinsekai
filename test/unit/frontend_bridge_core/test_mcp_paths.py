from __future__ import annotations

import pytest

from frontend_bridge_core import mcp
from frontend_bridge_core.mcp import _open_mcp_config_file, _validate_mcp_server
from ai.tools.mcp_tool_setup import _exact_mcp_text


def test_mcp_stdio_command_preserves_exact_path_text():
    server = _validate_mcp_server(
        {
            "command": "/opt/My Tools/mcp-server",
            "cwd": "servers/My MCP",
            "name_prefix": "demo_",
            "transport": "stdio",
        }
    )

    assert server["command"] == "/opt/My Tools/mcp-server"
    assert server["cwd"] == "servers/My MCP"


@pytest.mark.parametrize(
    ("transport", "field", "value"),
    [
        ("stdio", "command", " /opt/mcp-server"),
        ("stdio", "command", "/opt/mcp-server "),
        ("sse", "url", " https://mcp.example/sse"),
        ("streamable_http", "url", "https://mcp.example/api "),
    ],
)
def test_mcp_endpoints_reject_whitespace_aliases(transport, field, value):
    with pytest.raises(ValueError, match="surrounding whitespace"):
        _validate_mcp_server({"transport": transport, field: value})


def test_runtime_mcp_text_validator_never_trims_executable_path():
    assert _exact_mcp_text(
        "/opt/My Tools/mcp-server",
        field="MCP stdio command",
        required=True,
    ) == "/opt/My Tools/mcp-server"

    with pytest.raises(ValueError, match="surrounding whitespace"):
        _exact_mcp_text(
            " /opt/mcp-server",
            field="MCP stdio command",
            required=True,
        )


def test_mcp_stdio_working_directory_rejects_whitespace_aliases():
    with pytest.raises(ValueError, match="surrounding whitespace"):
        _validate_mcp_server(
            {
                "command": "python",
                "cwd": " servers/demo",
                "transport": "stdio",
            }
        )


def test_open_mcp_config_uses_identity_bound_default_application_helper(
    tmp_path,
    monkeypatch,
):
    config = tmp_path / "mcp.yaml"
    config.write_text("enabled: true\nservers: []\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr(mcp, "_mcp_config_path", lambda _state: config)
    monkeypatch.setattr(
        mcp,
        "open_with_default_application",
        lambda path: opened.append(path),
    )

    result = _open_mcp_config_file(object())

    assert opened == [config]
    assert result == {"path": config.as_posix()}
