"""Structural tool-manager contract shared with plugins."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ToolManager(Protocol):
    """Minimum host tool registry surface consumed by the SDK."""

    def register_function(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        group: str = "default",
        risk: str = "low",
    ) -> None: ...

    def get_definitions(self, groups: str | list[str] | None = None) -> list[dict[str, Any]]: ...

    def execute(self, name: str, arguments: dict[str, Any]) -> Any: ...
