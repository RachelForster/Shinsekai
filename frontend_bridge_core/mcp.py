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
from sdk.path_references import state_project_root
from sdk.process_launch import open_with_default_application


def _mcp_config_path(state=None):
    if state is None:
        return ensure_mcp_config_file()
    from config.mcp_config import resolve_mcp_config_path

    return resolve_mcp_config_path(project_root=state_project_root(state))


def _open_mcp_config_file(state=None) -> dict[str, str]:
    """Open the MCP configuration through the desktop platform adapter."""

    if state is None:
        path = ensure_mcp_config_file()
        webbrowser.open(path.resolve().as_uri())
    else:
        path = _mcp_config_path(state)
        if not path.is_file():
            from config.mcp_config import default_mcp_config, write_mcp_config

            write_mcp_config(default_mcp_config(), path)
        open_with_default_application(path)
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
