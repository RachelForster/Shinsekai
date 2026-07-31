"""MCP 配置文件读写（仅 PyYAML，不依赖 ``mcp`` 包）。"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml

from sdk.file_transactions import atomic_write_text, read_text_without_links
from sdk.path_contract import project_root as configured_project_root
from sdk.path_contract import (
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_project_output_path,
    resolve_project_path,
    validate_exact_path_text,
)

DEFAULT_MCP_CONFIG_PATH = Path("data/config/mcp.yaml")
_MCP_CONFIG_LOCK = threading.RLock()


def resolve_mcp_config_path(
    path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> Path:
    raw = os.fspath(DEFAULT_MCP_CONFIG_PATH if path is None else path)
    if not raw or raw != raw.strip() or any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in raw
    ):
        raise ValueError("MCP config path is empty or contains non-portable characters")
    root = (
        resolve_project_path(".", root=project_root)
        if project_root is not None
        else configured_project_root()
    )
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        require_symlink_free_absolute_path(
            candidate,
            field="MCP config path",
        )
    return resolve_project_output_path(raw, root=root)


def require_openable_mcp_config_path(path: str | Path) -> Path:
    """Revalidate a bound config path immediately before handing it to the OS."""

    return require_symlink_free_absolute_path(path, field="MCP config path")


def resolve_mcp_stdio_working_directory(
    value: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> Path:
    """Bind an MCP stdio working directory to one explicit project root.

    Missing values intentionally mean the project root.  Relative values are
    portable project references; absolute values retain their external
    identity.  In both cases every existing path component must be link-free
    so validation and process creation cannot address different directories.
    """

    root = (
        resolve_project_path(".", root=project_root)
        if project_root is not None
        else configured_project_root()
    )
    raw = "." if value in (None, "") else os.fspath(value)
    validate_exact_path_text(
        raw,
        field="MCP stdio working directory",
        allow_dot_root=True,
    )
    resolved = resolve_project_path(raw, root=root)
    if raw == ".":
        lexical = root
    else:
        expanded = Path(raw).expanduser()
        lexical = (
            expanded
            if expanded.is_absolute()
            else root.joinpath(*raw.replace("\\", "/").split("/"))
        )
    exact = require_directory_without_links(
        lexical,
        field="MCP stdio working directory",
        allow_filesystem_root=True,
    )
    if exact.resolve(strict=False) != resolved:
        raise PermissionError("MCP stdio working directory changed identity")
    return exact


def default_mcp_config() -> dict[str, Any]:
    return {"enabled": True, "default_call_timeout": 300.0, "servers": []}


def read_mcp_config(path: str | Path | None = None) -> dict[str, Any]:
    p = resolve_mcp_config_path(path)
    base = default_mcp_config()
    if not p.is_file():
        return base
    try:
        with _MCP_CONFIG_LOCK:
            raw = yaml.safe_load(read_text_without_links(p))
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


def write_mcp_config(data: dict[str, Any], path: str | Path | None = None) -> None:
    p = resolve_mcp_config_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": bool(data.get("enabled", True)),
        "default_call_timeout": float(data.get("default_call_timeout", 300)),
        "servers": data.get("servers") if isinstance(data.get("servers"), list) else [],
    }
    serialized = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    with _MCP_CONFIG_LOCK:
        atomic_write_text(p, serialized)
