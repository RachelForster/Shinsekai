from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from application.runtime.state import BridgeState
from application.runtime.tasks import _update_task


def _as_str_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _exact_mcp_text(
    value: Any,
    *,
    field: str,
    required: bool = False,
) -> str:
    raw = str(value or "")
    if raw != raw.strip() or any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in raw
    ):
        raise ValueError(
            f"{field} must not contain surrounding whitespace or control characters"
        )
    if required and not raw:
        raise ValueError(f"{field} is required")
    return raw


def _mcp_config_response(data: dict[str, Any] | None = None) -> dict[str, Any]:
    from config.mcp_config import DEFAULT_MCP_CONFIG_PATH, read_mcp_config

    cfg = read_mcp_config(DEFAULT_MCP_CONFIG_PATH) if data is None else data
    servers: list[dict[str, Any]] = []
    for raw in cfg.get("servers") or []:
        if not isinstance(raw, dict):
            continue
        transport = str(raw.get("transport") or "sse").strip().lower()
        if transport not in {"sse", "stdio", "streamable_http"}:
            transport = "sse"
        entry: dict[str, Any] = {
            "enabled": raw.get("enabled") is not False,
            "name_prefix": str(raw.get("name_prefix") or ""),
            "transport": transport,
        }
        group = str(raw.get("group") or "").strip()
        if group:
            entry["group"] = group
        if raw.get("call_timeout") is not None:
            try:
                value = float(raw.get("call_timeout"))
                if value > 0:
                    entry["call_timeout"] = value
            except (TypeError, ValueError):
                pass
        if transport in {"sse", "streamable_http"}:
            entry["url"] = str(raw.get("url") or "")
            entry["headers"] = _as_str_map(raw.get("headers"))
        else:
            entry["command"] = str(raw.get("command") or "")
            entry["args"] = _as_str_list(raw.get("args"))
            entry["env"] = _as_str_map(raw.get("env"))
            cwd = str(raw.get("cwd") or "")
            if cwd:
                entry["cwd"] = cwd
        servers.append(entry)
    try:
        default_timeout = float(cfg.get("default_call_timeout", 300))
    except (TypeError, ValueError):
        default_timeout = 300.0
    return {
        "default_call_timeout": default_timeout,
        "enabled": cfg.get("enabled") is not False,
        "path": DEFAULT_MCP_CONFIG_PATH.as_posix(),
        "servers": servers,
    }


def _validate_mcp_server(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("MCP server must be an object")
    transport = _exact_mcp_text(
        raw.get("transport") or "sse",
        field="MCP transport",
        required=True,
    ).lower()
    if transport not in {"sse", "stdio", "streamable_http"}:
        raise ValueError(f"Unknown MCP transport: {transport!r}")
    entry: dict[str, Any] = {
        "enabled": raw.get("enabled") is not False,
        "name_prefix": _exact_mcp_text(
            raw.get("name_prefix"),
            field="MCP name prefix",
        ),
        "transport": transport,
    }
    group = _exact_mcp_text(raw.get("group"), field="MCP group")
    if group:
        entry["group"] = group
    if raw.get("call_timeout") not in (None, ""):
        try:
            timeout = float(raw.get("call_timeout"))
        except (TypeError, ValueError) as exc:
            raise ValueError("MCP call_timeout must be a number") from exc
        if timeout > 0:
            entry["call_timeout"] = timeout

    if transport in {"sse", "streamable_http"}:
        url = _exact_mcp_text(
            raw.get("url"),
            field="MCP HTTP URL",
            required=True,
        )
        entry["url"] = url
        headers = raw.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("MCP headers must be an object")
        entry["headers"] = _as_str_map(headers)
    else:
        command = _exact_mcp_text(
            raw.get("command"),
            field="MCP stdio command",
            required=True,
        )
        args = raw.get("args")
        env = raw.get("env")
        if args is not None and not isinstance(args, list):
            raise ValueError("MCP stdio args must be an array")
        if env is not None and not isinstance(env, dict):
            raise ValueError("MCP stdio env must be an object")
        entry["command"] = command
        entry["args"] = _as_str_list(args)
        entry["env"] = _as_str_map(env)
        cwd = _exact_mcp_text(
            raw.get("cwd"),
            field="MCP stdio working directory",
        )
        if cwd:
            entry["cwd"] = cwd
    return entry


def _validate_mcp_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = payload.get("config", payload)
    if not isinstance(cfg, dict):
        raise ValueError("MCP config payload must be an object")
    try:
        default_timeout = float(cfg.get("default_call_timeout", 300))
    except (TypeError, ValueError) as exc:
        raise ValueError("MCP default_call_timeout must be a number") from exc
    if default_timeout <= 0:
        raise ValueError("MCP default_call_timeout must be greater than 0")
    servers = cfg.get("servers") or []
    if not isinstance(servers, list):
        raise ValueError("MCP servers must be a list")
    return {
        "default_call_timeout": default_timeout,
        "enabled": cfg.get("enabled") is not False,
        "servers": [_validate_mcp_server(item) for item in servers],
    }


def _preview_mcp_tools_from_payload(
    state: BridgeState, task_id: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    from ai.tools.mcp_tool_setup import preview_mcp_tools_from_config
    from config.mcp_config import write_mcp_config

    cfg = _validate_mcp_config_payload(payload)
    _update_task(
        state, task_id, message="正在写入临时 MCP 配置。", phase="write", progress=0.2
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        write_mcp_config(cfg, temp_path)
        _update_task(
            state,
            task_id,
            message="正在连接 MCP 服务并枚举工具。",
            phase="probe",
            progress=0.55,
        )
        rows = preview_mcp_tools_from_config(temp_path)
        valid = [dict(item) for item in rows if isinstance(item, dict)]
        _update_task(
            state, task_id, message=f"已获取 {len(valid)} 个 MCP 工具。", progress=0.92
        )
        return valid
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _save_and_apply_mcp_config(
    state: BridgeState, task_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    from ai.tools.mcp_tool_setup import reload_mcp_tools_from_config
    from ai.tools.tool_manager import ToolManager
    from config.mcp_config import DEFAULT_MCP_CONFIG_PATH, write_mcp_config

    cfg = _validate_mcp_config_payload(payload)
    _update_task(
        state,
        task_id,
        message="正在写入 data/config/mcp.yaml。",
        phase="write",
        progress=0.35,
    )
    write_mcp_config(cfg, DEFAULT_MCP_CONFIG_PATH)
    _update_task(
        state, task_id, message="正在重新注册 MCP 工具。", phase="reload", progress=0.72
    )
    reload_mcp_tools_from_config(ToolManager(), DEFAULT_MCP_CONFIG_PATH)
    return _mcp_config_response(cfg)


def ensure_mcp_config_file() -> Path:
    """Create the MCP configuration when missing and return its path."""

    from config.mcp_config import (
        DEFAULT_MCP_CONFIG_PATH,
        default_mcp_config,
        write_mcp_config,
    )

    path = DEFAULT_MCP_CONFIG_PATH
    if not path.is_file():
        write_mcp_config(default_mcp_config(), path)
    return path
