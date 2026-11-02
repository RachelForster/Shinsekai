"""Schema defaults and persistence for ``data/config/mcp.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_MCP_CONFIG_PATH = Path("data/config/mcp.yaml")


def default_mcp_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "default_call_timeout": 300.0,
        "servers": [],
    }


def read_mcp_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_MCP_CONFIG_PATH
    config = default_mcp_config()
    if not config_path.is_file():
        return config
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config
    if not isinstance(raw, dict):
        return config
    if "enabled" in raw:
        config["enabled"] = bool(raw["enabled"])
    if raw.get("default_call_timeout") is not None:
        try:
            config["default_call_timeout"] = float(raw["default_call_timeout"])
        except (TypeError, ValueError):
            pass
    servers = raw.get("servers")
    if isinstance(servers, list):
        config["servers"] = [server for server in servers if isinstance(server, dict)]
    return config


def write_mcp_config(
    data: dict[str, Any],
    path: Path | None = None,
) -> None:
    config_path = path or DEFAULT_MCP_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": bool(data.get("enabled", True)),
        "default_call_timeout": float(data.get("default_call_timeout", 300)),
        "servers": (
            data.get("servers") if isinstance(data.get("servers"), list) else []
        ),
    }
    with config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            payload,
            file,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
