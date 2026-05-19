from __future__ import annotations

import os

import pytest

from llm.tools import mcp_config_file
from llm.tools.mcp_config_file import (
    MCPStdioCommandError,
    mask_mcp_stdio_env_for_display,
    normalize_mcp_stdio_command,
    validate_mcp_stdio_servers,
)


pytestmark = pytest.mark.unit


def test_stdio_command_rejects_shell_launcher() -> None:
    with pytest.raises(MCPStdioCommandError, match="not allowed"):
        normalize_mcp_stdio_command("bash", ["-lc", "echo owned"])


def test_stdio_command_rejects_shell_like_single_string() -> None:
    with pytest.raises(MCPStdioCommandError, match="whitespace"):
        normalize_mcp_stdio_command("python -m mcp_server")


def test_stdio_command_rejects_relative_path(tmp_path) -> None:
    server = tmp_path / "server.py"
    server.write_text("print('server')\n", encoding="utf-8")

    with pytest.raises(MCPStdioCommandError, match="absolute"):
        normalize_mcp_stdio_command("./server.py")


def test_stdio_command_accepts_absolute_executable(tmp_path) -> None:
    server = tmp_path / "server"
    server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    server.chmod(server.stat().st_mode | 0o111)

    normalized = normalize_mcp_stdio_command(str(server), ["--stdio"], {"SAFE": "1"})

    assert normalized.command == str(server)
    assert normalized.args == ["--stdio"]
    assert normalized.env == {"SAFE": "1"}


def test_stdio_command_accepts_allowlisted_bare_command_when_on_path(monkeypatch) -> None:
    monkeypatch.setattr(mcp_config_file.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    normalized = normalize_mcp_stdio_command("python3", ["-m", "example_mcp"])

    assert normalized.command == "/usr/bin/python3"
    assert normalized.args == ["-m", "example_mcp"]


def test_stdio_command_rejects_inline_eval_for_allowlisted_launchers(monkeypatch) -> None:
    monkeypatch.setattr(mcp_config_file.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    with pytest.raises(MCPStdioCommandError, match="inline eval"):
        normalize_mcp_stdio_command("python3", ["-c", "print('owned')"])


def test_validate_stdio_servers_skips_disabled_entries() -> None:
    data = {
        "enabled": True,
        "servers": [
            {"enabled": False, "transport": "stdio", "command": "bash"},
        ],
    }

    validate_mcp_stdio_servers(data)


def test_validate_stdio_servers_rejects_active_bad_entry() -> None:
    data = {
        "enabled": True,
        "servers": [
            {"transport": "stdio", "command": "bash"},
        ],
    }

    with pytest.raises(MCPStdioCommandError, match="server #1"):
        validate_mcp_stdio_servers(data)


def test_mask_stdio_env_hides_obvious_secret_values() -> None:
    masked = mask_mcp_stdio_env_for_display(
        {"API_KEY": "sk-secret", "PUBLIC_HOST": "localhost"}
    )

    assert masked == {"API_KEY": "***", "PUBLIC_HOST": "localhost"}
    assert "sk-secret" not in str(masked)


def test_stdio_env_rejects_invalid_key() -> None:
    with pytest.raises(MCPStdioCommandError, match="env key"):
        normalize_mcp_stdio_command(
            os.devnull,
            [],
            {"BAD-KEY": "value"},
        )
