"""Pure MCP configuration model for ``data/config/mcp.yaml``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List

from pydantic import BaseModel, Field, model_validator


class McpConfig(BaseModel):
    """Structured MCP server configuration."""

    enabled: bool = Field(default=True, description="是否启用 MCP 工具支持")
    default_call_timeout: float = Field(default=300.0, description="默认工具调用超时时间（秒）")
    servers: List[Dict[str, Any]] = Field(
        default_factory=list, description="已配置的 MCP Server 定义列表"
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_mcp_mapping(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return {}
        out: Dict[str, Any] = {}
        if "enabled" in value and value["enabled"] is not None:
            out["enabled"] = bool(value["enabled"])
        raw_timeout = value.get("default_call_timeout")
        if raw_timeout is not None:
            try:
                out["default_call_timeout"] = float(raw_timeout)
            except (TypeError, ValueError):
                pass
        raw_servers = value.get("servers")
        if isinstance(raw_servers, list):
            out["servers"] = [dict(item) for item in raw_servers if isinstance(item, dict)]
        return out


__all__ = ["McpConfig"]
