"""Schema defaults and atomic persistence for ``data/config/mcp.yaml``."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any

import yaml

from config.models.mcp_settings import McpConfig
from sdk.file_io import durable_mkdir, durable_rename

DEFAULT_MCP_CONFIG_PATH = Path("data/config/mcp.yaml")


def default_mcp_config() -> dict[str, Any]:
    return McpConfig().model_dump(mode="python")


def read_mcp_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_MCP_CONFIG_PATH
    config = McpConfig()
    if not config_path.is_file():
        return config.model_dump(mode="python")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config.model_dump(mode="python")
    if not isinstance(raw, dict):
        return config.model_dump(mode="python")
    return McpConfig.model_validate(raw).model_dump(mode="python")


def write_mcp_config(
    data: dict[str, Any],
    path: Path | None = None,
) -> None:
    config_path = path or DEFAULT_MCP_CONFIG_PATH
    durable_mkdir(config_path.parent)
    model = McpConfig.model_validate(data if isinstance(data, dict) else {})
    payload = model.model_dump(mode="json")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            yaml.safe_dump(
                payload,
                file,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            file.flush()
            os.fsync(file.fileno())
        durable_rename(temporary_path, config_path, replace=True)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
