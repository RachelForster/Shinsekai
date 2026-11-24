"""Pure UI runtime state model stored in ``data/state/ui_state.json``."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from config.models.common import DefaultIfNone


class UiRuntimeState(BaseModel):
    """High-frequency UI window geometry and last template launch state."""

    version: DefaultIfNone[int] = Field(default=1, ge=1)
    chat_window_geometry_b64: DefaultIfNone[str] = Field(
        default="",
        description="聊天主窗口上次关闭时的 saveGeometry Base64",
    )
    template_last_launch: Optional[Dict[str, Any]] = Field(
        default=None,
        description="上次启动聊天时的模板与角色选项快照",
    )


__all__ = ["UiRuntimeState"]
