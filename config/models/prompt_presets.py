"""Pure user prompt preset models for ``data/config/user_prompt_presets.json``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def normalize_applied_presets_list(raw: Any) -> list[dict[str, Any]]:
    """Normalize applied preset snapshots stored in template metadata or UI launch state."""
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        preset_id = str(entry.get("id") or "").strip()[:128]
        if not preset_id or preset_id in seen_ids:
            continue
        seen_ids.add(preset_id)
        name = str(entry.get("name") or "").strip()[:64]
        group = str(entry.get("group") or "").strip()[:64]
        color = str(entry.get("color") or "").strip()[:32]
        content = str(entry.get("content") or "").replace("\r\n", "\n")
        item: dict[str, Any] = {
            "id": preset_id,
            "name": name or preset_id,
            "content": content,
        }
        if group:
            item["group"] = group
        if color:
            item["color"] = color
        items.append(item)
    return items


def normalize_user_prompt_presets_dict(raw: Any) -> dict[str, Any]:
    """Normalize raw JSON/dict input into ``{"groups": [...], "presets": [...]}``."""
    data = raw if isinstance(raw, Mapping) else {}
    groups: list[str] = []
    seen_groups: set[str] = set()
    raw_groups = data.get("groups")
    if isinstance(raw_groups, list):
        for item in raw_groups:
            group = str(item or "").strip()[:64]
            if group and group not in seen_groups:
                seen_groups.add(group)
                groups.append(group)

    presets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    raw_presets = data.get("presets")
    if isinstance(raw_presets, list):
        for entry in raw_presets:
            if not isinstance(entry, Mapping):
                continue
            preset_id = str(entry.get("id") or "").strip()[:128]
            name = str(entry.get("name") or "").strip()[:64]
            if not preset_id or not name or preset_id in seen_ids:
                continue
            seen_ids.add(preset_id)
            group = str(entry.get("group") or "").strip()[:64]
            if group and group not in seen_groups:
                seen_groups.add(group)
                groups.append(group)
            color = str(entry.get("color") or "").strip()[:32]
            content = str(entry.get("content") or "").replace("\r\n", "\n")
            preset: dict[str, Any] = {
                "id": preset_id,
                "name": name,
                "group": group,
                "content": content,
            }
            if color:
                preset["color"] = color
            presets.append(preset)
    return {"groups": groups, "presets": presets}


class UserPromptPreset(BaseModel):
    """Single reusable user prompt preset definition."""

    id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=64)
    group: str = Field(default="", max_length=64)
    content: str = Field(default="")
    color: Optional[str] = Field(default=None, max_length=32)

    @field_validator("color", mode="before")
    @classmethod
    def _clean_optional_color(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()[:32]
        return cleaned or None


class UserPromptPresetLibrary(BaseModel):
    """Structured user prompt preset groups and ordered preset definitions."""

    groups: List[str] = Field(default_factory=list)
    presets: List[UserPromptPreset] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_library(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            coerced = dict(value)
            if isinstance(coerced.get("presets"), list):
                coerced["presets"] = [
                    item.model_dump(mode="python", exclude_none=True)
                    if isinstance(item, BaseModel)
                    else item
                    for item in coerced["presets"]
                ]
            return normalize_user_prompt_presets_dict(coerced)
        return normalize_user_prompt_presets_dict(value)

    def to_payload(self) -> Dict[str, Any]:
        """Serialize to the canonical frontend JSON contract."""
        return self.model_dump(mode="json", exclude_none=True)


__all__ = [
    "UserPromptPreset",
    "UserPromptPresetLibrary",
    "normalize_applied_presets_list",
    "normalize_user_prompt_presets_dict",
]
