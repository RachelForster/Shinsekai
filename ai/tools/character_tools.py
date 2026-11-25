"""Character lookup tool wrappers backed by ``CharacterCatalogPort``."""

from __future__ import annotations

import threading
from typing import Any

from config.schema import (
    SELF_PERSONA_NAME,
    is_self_persona_name,
    resolve_character_by_prompt_name,
    resolve_character_prompt_name,
)
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
        cleaned = character_name.strip()
        char = self._catalog.get_by_name(cleaned)
        if char is None:
            self_char = self._catalog.get_by_name(SELF_PERSONA_NAME)
            if self_char is not None and is_self_persona_name(getattr(self_char, "name", "")):
                dname = str(getattr(self_char, "display_name", "") or "").strip()
                if dname and dname.casefold() == cleaned.casefold():
                    char = self_char
        if not char:
            return {"error": f"找不到角色: {character_name}"}
        all_names = [c.name for c in self._catalog.list_all()]
        result: dict[str, Any] = {
            "name": resolve_character_prompt_name(char, colliding_names=all_names),
            "setting": char.character_setting,
            "emotion_tags": char.emotion_tags,
        }
        if is_self_persona_name(char.name):
            result["is_user_self_persona"] = True
        return result

    def get_available_character_name_list(self) -> list[str]:
        chars = list(self._catalog.list_all())
        all_names = [c.name for c in chars]
        return [resolve_character_prompt_name(c, colliding_names=all_names) for c in chars]


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
    char = resolve_character_by_prompt_name(handler, character_name)
    if not char:
        return {"error": f"找不到角色: {character_name}"}
    all_names = [
        getattr(c, "name", "")
        for c in (getattr(getattr(handler, "config", None), "characters", ()) or ())
    ]
    result: dict[str, Any] = {
        "name": resolve_character_prompt_name(char, colliding_names=all_names),
        "setting": char.character_setting,
        "emotion_tags": char.emotion_tags,
    }
    if is_self_persona_name(getattr(char, "name", "")):
        result["is_user_self_persona"] = True
    return result


@tool(group="character")
def get_available_character_name_list():
    """
    获取所有可用角色名字的列表。
    """
    handler = _resolve_handler()
    if isinstance(handler, CharacterToolHandler):
        return handler.get_available_character_name_list()
    chars = list(getattr(getattr(handler, "config", None), "characters", ()) or ())
    all_names = [getattr(c, "name", "") for c in chars]
    return [resolve_character_prompt_name(c, colliding_names=all_names) for c in chars]


__all__ = [
    "CharacterToolHandler",
    "bind_character_tool_catalog",
    "get_available_character_name_list",
    "get_character_info",
]