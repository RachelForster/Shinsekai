"""Transport adapters for MCP application use cases."""

from __future__ import annotations

import webbrowser

from application import mcp as _application_mcp
from application.mcp import (
    _mcp_config_response,
    _preview_mcp_tools_from_payload,
    _save_and_apply_mcp_config,
    ensure_mcp_config_file,
)


def _open_mcp_config_file() -> dict[str, str]:
    """Open the MCP configuration through the desktop platform adapter."""

    path = ensure_mcp_config_file()
    webbrowser.open(path.resolve().as_uri())
    return {"path": path.as_posix()}


def __getattr__(name: str):
    """Preserve access to application helpers exposed by the old alias."""

    return getattr(_application_mcp, name)


__all__ = [
    "_mcp_config_response",
    "_open_mcp_config_file",
    "_preview_mcp_tools_from_payload",
    "_save_and_apply_mcp_config",
]
