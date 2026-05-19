"""MCP 配置文件读写与 stdio 本机命令边界（仅 PyYAML，不依赖 ``mcp`` 包）。"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MCP_CONFIG_PATH = Path("data/config/mcp.yaml")

_COMMAND_META_RE = re.compile(r"[\x00\r\n;&|`$<>]")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_ENV_RE = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIAL|AUTH|BEARER)", re.IGNORECASE
)

BLOCKED_MCP_STDIO_COMMAND_NAMES = frozenset(
    {
        "bash",
        "bash.exe",
        "cmd",
        "cmd.exe",
        "cscript",
        "cscript.exe",
        "dash",
        "fish",
        "ksh",
        "mshta",
        "mshta.exe",
        "open",
        "osascript",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "sh.exe",
        "wscript",
        "wscript.exe",
        "xdg-open",
        "zsh",
    }
)

# Common MCP launchers are allowed by bare name for usability. Custom binaries must
# be provided as absolute executable paths so a config cannot silently depend on a
# project-local relative command or ambiguous shell string.
ALLOWED_MCP_STDIO_BARE_COMMANDS = frozenset(
    {
        "bun",
        "deno",
        "docker",
        "node",
        "npm",
        "npx",
        "pnpm",
        "python",
        "python3",
        "pythonw",
        "uv",
        "uvx",
        "yarn",
    }
)

_INLINE_EVAL_FLAGS_BY_COMMAND = {
    "bun": {"-e", "--eval"},
    "deno": {"eval"},
    "node": {"-e", "--eval", "-p", "--print"},
    "python": {"-c"},
    "pythonw": {"-c"},
}


class MCPStdioCommandError(ValueError):
    """Raised when a stdio MCP entry would launch an unsafe local command."""


@dataclass(frozen=True)
class NormalizedMCPStdioCommand:
    command: str
    args: list[str]
    env: dict[str, str] | None


def default_mcp_config() -> dict[str, Any]:
    return {"enabled": True, "default_call_timeout": 300.0, "servers": []}


def read_mcp_config(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_MCP_CONFIG_PATH
    base = default_mcp_config()
    if not p.is_file():
        return base
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(raw, dict):
        return base
    if "enabled" in raw:
        base["enabled"] = bool(raw["enabled"])
    if raw.get("default_call_timeout") is not None:
        try:
            base["default_call_timeout"] = float(raw["default_call_timeout"])
        except (TypeError, ValueError):
            pass
    servers = raw.get("servers")
    if isinstance(servers, list):
        base["servers"] = [x for x in servers if isinstance(x, dict)]
    return base


def write_mcp_config(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or DEFAULT_MCP_CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": bool(data.get("enabled", True)),
        "default_call_timeout": float(data.get("default_call_timeout", 300)),
        "servers": data.get("servers") if isinstance(data.get("servers"), list) else [],
    }
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            payload,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def _command_name(command: str) -> str:
    return Path(command).name.lower()


def _has_path_separator(command: str) -> bool:
    return "/" in command or "\\" in command


def _validate_command_token(command: str) -> None:
    if not command.strip():
        raise MCPStdioCommandError("MCP stdio command is required.")
    if _COMMAND_META_RE.search(command):
        raise MCPStdioCommandError(
            "MCP stdio command must be a single executable; put flags in args."
        )
    if any(ch.isspace() for ch in command):
        raise MCPStdioCommandError(
            "MCP stdio command must not contain whitespace; put flags in args."
        )


def _blocked_inline_flags(command_name: str) -> set[str]:
    if command_name.startswith("python"):
        return _INLINE_EVAL_FLAGS_BY_COMMAND["python"]
    return _INLINE_EVAL_FLAGS_BY_COMMAND.get(command_name, set())


def _validate_stdio_args(command_name: str, args: list[str]) -> None:
    blocked_eval = _blocked_inline_flags(command_name)
    for arg in args:
        if "\x00" in arg or "\r" in arg or "\n" in arg:
            raise MCPStdioCommandError("MCP stdio args must not contain control characters.")
        if arg in blocked_eval:
            raise MCPStdioCommandError(
                f"MCP stdio launcher {command_name!r} must not use inline eval flag {arg!r}."
            )


def normalize_mcp_stdio_env(raw: Any) -> dict[str, str] | None:
    """Normalize stdio env and reject keys subprocess cannot represent safely."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise MCPStdioCommandError("MCP stdio env must be a mapping.")
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k)
        if not _ENV_KEY_RE.fullmatch(key):
            raise MCPStdioCommandError(f"Invalid MCP stdio env key: {key!r}")
        val = str(v)
        if "\x00" in val:
            raise MCPStdioCommandError(f"MCP stdio env value for {key!r} contains NUL.")
        out[key] = val
    return out or None


def mask_mcp_stdio_env_for_display(raw: Any) -> dict[str, str]:
    """Return env values safe for logs/UI previews; never expose obvious secrets."""
    env = normalize_mcp_stdio_env(raw)
    if not env:
        return {}
    return {
        key: "***" if _SENSITIVE_ENV_RE.search(key) else value
        for key, value in env.items()
    }


def normalize_mcp_stdio_command(
    command: str,
    args: list[str] | None = None,
    env: Any = None,
) -> NormalizedMCPStdioCommand:
    """Validate and normalize a stdio MCP local process launch.

    Accepted commands are either absolute executable paths or a narrow set of
    common MCP launchers resolved through PATH. Relative paths and shell
    launchers are rejected before any process can be started.
    """
    raw_command = str(command or "").strip()
    _validate_command_token(raw_command)
    raw_args = [str(x) for x in args] if isinstance(args, list) else []
    raw_env = normalize_mcp_stdio_env(env)

    expanded = Path(raw_command).expanduser()
    name = _command_name(raw_command)
    if name in BLOCKED_MCP_STDIO_COMMAND_NAMES:
        raise MCPStdioCommandError(
            f"MCP stdio command {name!r} is a shell/system launcher and is not allowed."
        )

    if expanded.is_absolute():
        if not expanded.is_file():
            raise MCPStdioCommandError(
                f"MCP stdio command path does not exist or is not a file: {raw_command}"
            )
        if not os.access(expanded, os.X_OK):
            raise MCPStdioCommandError(
                f"MCP stdio command path is not executable: {raw_command}"
            )
        normalized = str(expanded)
        normalized_name = _command_name(normalized)
    else:
        if _has_path_separator(raw_command):
            raise MCPStdioCommandError(
                "MCP stdio command must be an absolute executable path; relative paths are not allowed."
            )
        if name not in ALLOWED_MCP_STDIO_BARE_COMMANDS:
            allowed = ", ".join(sorted(ALLOWED_MCP_STDIO_BARE_COMMANDS))
            raise MCPStdioCommandError(
                f"MCP stdio bare command {raw_command!r} is not allowed. "
                f"Use an absolute executable path or one of: {allowed}."
            )
        resolved = shutil.which(raw_command)
        if not resolved:
            raise MCPStdioCommandError(
                f"MCP stdio command {raw_command!r} was not found on PATH."
            )
        normalized = resolved
        normalized_name = name

    _validate_stdio_args(normalized_name, raw_args)
    return NormalizedMCPStdioCommand(normalized, raw_args, raw_env)


def normalize_mcp_stdio_entry(entry: dict[str, Any]) -> NormalizedMCPStdioCommand:
    if not isinstance(entry, dict):
        raise MCPStdioCommandError("MCP stdio entry must be a mapping.")
    command = str(entry.get("command") or "").strip()
    args_raw = entry.get("args")
    args = [str(x) for x in args_raw] if isinstance(args_raw, list) else []
    return normalize_mcp_stdio_command(command, args, entry.get("env"))


def validate_mcp_stdio_servers(data: dict[str, Any], *, active_only: bool = True) -> None:
    """Validate every stdio server that may be activated by save/preview/reload."""
    if data.get("enabled") is False:
        return
    servers = data.get("servers")
    if not isinstance(servers, list):
        return
    for i, entry in enumerate(servers):
        if not isinstance(entry, dict):
            continue
        if active_only and entry.get("enabled") is False:
            continue
        if str(entry.get("transport") or "").strip().lower() != "stdio":
            continue
        try:
            normalize_mcp_stdio_entry(entry)
        except MCPStdioCommandError as exc:
            raise MCPStdioCommandError(f"MCP stdio server #{i + 1}: {exc}") from exc
