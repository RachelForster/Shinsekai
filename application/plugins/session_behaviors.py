"""Application query helpers for plugin-registered SessionBehavior contributions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plugin_system.host import get_plugin_manager


def _to_json_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def list_session_behavior_contributions() -> list[dict[str, Any]]:
    """Return metadata dicts for all plugin-registered SessionBehaviors."""
    manager = get_plugin_manager()
    if manager is None:
        return []
    collect = getattr(manager, "collect_session_behaviors", None)
    if not callable(collect):
        return []
    items: list[dict[str, Any]] = []
    for contribution in collect():
        behavior_id = str(getattr(contribution, "behavior_id", "") or "").strip()
        if not behavior_id:
            continue
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        raw_i18n = _to_json_dict(getattr(contribution, "i18n", None))
        items.append(
            {
                "behaviorId": behavior_id,
                "pluginId": plugin_id,
                "name": str(getattr(contribution, "name", "") or behavior_id).strip(),
                "description": str(
                    getattr(contribution, "description", "") or ""
                ).strip(),
                "defaultConfig": _to_json_dict(
                    getattr(contribution, "default_config", None)
                ),
                **({"i18n": raw_i18n} if raw_i18n else {}),
            }
        )
    return items


def find_session_behavior_plugin_id(behavior_id: str) -> str:
    """Resolve the owning plugin_id for a registered SessionBehavior, or '' if absent."""
    target = str(behavior_id or "").strip()
    if not target:
        return ""
    manager = get_plugin_manager()
    if manager is None:
        return ""
    finder = getattr(manager, "find_session_behavior", None)
    if not callable(finder):
        return ""
    contribution = finder(target)
    if contribution is None:
        return ""
    return str(getattr(contribution, "plugin_id", "") or "").strip()


__all__ = [
    "find_session_behavior_plugin_id",
    "list_session_behavior_contributions",
]
