"""MCP 配置文件读写（仅 PyYAML，不依赖 ``mcp`` 包）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_MCP_CONFIG_PATH = Path("data/config/mcp.yaml")


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
