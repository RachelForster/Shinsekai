"""Character lookup tool wrappers backed by ``CharacterCatalogPort``."""

from __future__ import annotations

import threading
from typing import Any

from core.storage.stores import CharacterCatalogPort
from sdk.tool_registry import tool

_catalog_lock = threading.RLock()
_bound_catalog: CharacterCatalogPort | None = None


class CharacterToolHandler:
    """Stateless character lookup adapter consuming only ``CharacterCatalogPort``."""

    def __init__(self, catalog: CharacterCatalogPort) -> None:
        self._catalog = catalog

    def get_character_info(self, character_name: str = "") -> dict[str, Any]:
        if not character_name or not character_name.strip():
            return {
                "error": "未提供角色名称。请先设定character_name参数，或调用 get_available_character_name_list 获取可用角色列表。"
            }
        char = self._catalog.get_by_name(character_name)
        if not char:
            return {"error": f"找不到角色: {character_name}"}
        return {
            "name": char.name,
            "setting": char.character_setting,
            "emotion_tags": char.emotion_tags,
        }

    def get_available_character_name_list(self) -> list[str]:
        return [char.name for char in self._catalog.list_all()]


def bind_character_tool_catalog(catalog: CharacterCatalogPort | None) -> None:
    """Bind or clear the active ``CharacterCatalogPort`` for character lookup tools."""
    with _catalog_lock:
        global _bound_catalog
        _bound_catalog = catalog


def __getattr__(name: str) -> Any:
    if name == "config_manager":
        from config.config_manager import ConfigManager

        return ConfigManager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _resolve_handler() -> CharacterToolHandler | Any:
    override = globals().get("config_manager")
    if override is not None:
        return override
    with _catalog_lock:
        catalog = _bound_catalog
    if catalog is not None:
        return CharacterToolHandler(catalog)
    from config.config_manager import ConfigManager

    return ConfigManager()


@tool(group="character")
def get_character_info(character_name: str = ""):
    """
    获取特定角色的详细背景设定、性格特点及立绘id和对应的情绪标注。
    当你忘记了某个角色的设定和立绘时，可以调用这个工具来查询。输入角色名，输出该角色的详细信息。如果在system中出现该人物，请不要调用这个工具。
    注意：调用时必须在 character_name 参数中提供角色姓名。
    """
    handler = _resolve_handler()
    if isinstance(handler, CharacterToolHandler):
        return handler.get_character_info(character_name)
    if not character_name or not character_name.strip():
        return {
            "error": "未提供角色名称。请先设定character_name参数，或调用 get_available_character_name_list 获取可用角色列表。"
        }
    char = handler.get_character_by_name(character_name)
    if not char:
        return {"error": f"找不到角色: {character_name}"}
    return {
        "name": char.name,
        "setting": char.character_setting,
        "emotion_tags": char.emotion_tags,
    }


@tool(group="character")
def get_available_character_name_list():
    """
    获取所有可用角色名字的列表。
    """
    handler = _resolve_handler()
    if isinstance(handler, CharacterToolHandler):
        return handler.get_available_character_name_list()
    return [char.name for char in handler.config.characters]


__all__ = [
    "CharacterToolHandler",
    "bind_character_tool_catalog",
    "get_available_character_name_list",
    "get_character_info",
]