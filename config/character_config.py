"""Compatibility wrapper delegating directly to the ``Character`` Pydantic schema."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from config.models import Character
from config.sprite_voice import normalize_sprite_voice_types

_PACKAGE_EXCLUDED_FIELDS = {"id", "display_name", "is_builtin", "pinned", "undeletable"}


class CharacterConfig:
    """Pass-through legacy wrapper backed by ``Character`` (no manual field enumeration)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raw: dict[str, Any] = dict(kwargs)
        positional_keys = ("name", "color", "sprite_prefix")
        for idx, val in enumerate(args):
            if idx < len(positional_keys):
                raw[positional_keys[idx]] = val

        # Preserve explicit None for optional model paths & empty relation_graph dict semantics
        normalized_input = normalize_sprite_voice_types(deepcopy(raw))
        explicit_none_paths = {
            k: normalized_input[k]
            for k in ("gpt_model_path", "sovits_model_path", "refer_audio_path", "prompt_text", "prompt_lang")
            if k in normalized_input and normalized_input[k] is None
        }
        model_input = {**normalized_input}
        for k in explicit_none_paths:
            model_input.pop(k, None)

        model = Character.model_validate(model_input)
        dumped = model.model_dump(mode="json", exclude=_PACKAGE_EXCLUDED_FIELDS)
        # Keep portrait_crop None when omitted or None in legacy dict inputs if caller passed None
        if raw.get("portrait_crop") is None and "portrait_crop" in raw:
            dumped["portrait_crop"] = None
        for k, v in explicit_none_paths.items():
            dumped[k] = v
        # Keep plain empty dict for empty relation_graph when passed as None/{} for compat
        if not dumped["relation_graph"].get("nodes") and not dumped["relation_graph"].get("edges"):
            dumped["relation_graph"] = {}
        # Ensure YAML-safe dict serialization on nested avatars even if callers passed ModelSprites
        for attr, val in dumped.items():
            setattr(self, attr, val)

    def to_character(self) -> Character:
        """Convert this compatibility wrapper back into a validated ``Character`` model."""
        return Character.model_validate(normalize_sprite_voice_types(dict(self.__dict__)))

    @staticmethod
    def read_from_files(path: str) -> list["CharacterConfig"]:
        with open(path, "r", encoding="utf-8") as file:
            config_data = yaml.safe_load(file) or []
        characters = []
        for char_data in config_data:
            if not all(key in char_data for key in ("name", "color", "sprite_prefix")):
                raise ValueError("YAML配置缺少必需字段（name, color, sprite_prefix）")
            characters.append(CharacterConfig.parse_dic(char_data=char_data))
        return characters

    @staticmethod
    def parse_dic(char_data: dict[str, Any]) -> "CharacterConfig":
        normalized = normalize_sprite_voice_types(deepcopy(dict(char_data)))
        return CharacterConfig(**normalized)
