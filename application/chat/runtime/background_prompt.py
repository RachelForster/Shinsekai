"""Resolve the displayed background into data for the user prompt section."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ai.llm.template.core import PROMPT_CATALOG
from ai.llm.template.integrations.localization import resolve_template_locale
from core.media.asset_tags import tag_contents
from sdk.lang import normalize_lang


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path).replace("\\", "/")))


def current_background_context(
    runtime: Any,
    *,
    locale: str | None = None,
) -> dict[str, str | int] | None:
    path = getattr(runtime.ui_update_manager, "current_background_path", None)
    if path is not None and not isinstance(path, (str, Path)):
        return None
    if not path:
        return None
    effective_locale = (
        normalize_lang(locale)
        if locale
        else resolve_template_locale(getattr(runtime, "config", None))
    )
    key_image = PROMPT_CATALOG.translate("session.bg_key_image", locale=effective_locale)
    key_group = PROMPT_CATALOG.translate("session.bg_key_group", locale=effective_locale)
    key_index = PROMPT_CATALOG.translate("session.bg_key_index", locale=effective_locale)
    key_desc = PROMPT_CATALOG.translate("session.bg_key_description", locale=effective_locale)
    details: dict[str, str | int] = {key_image: Path(str(path).replace("\\", "/")).name}
    backgrounds = [getattr(runtime, "background", None)]
    configured = getattr(getattr(runtime.config, "config", None), "background_list", [])
    if isinstance(configured, (list, tuple)):
        backgrounds.extend(configured)
    for background in backgrounds:
        sprites = getattr(background, "sprites", [])
        if not isinstance(sprites, (list, tuple)):
            continue
        for index, sprite in enumerate(sprites):
            asset_path = sprite.get("path") if isinstance(sprite, dict) else getattr(sprite, "path", None)
            if not isinstance(asset_path, (str, Path)) or not asset_path:
                continue
            if _path_key(asset_path) != _path_key(path):
                continue
            details.update({key_group: str(background.name), key_index: index + 1})
            description = tag_contents(getattr(background, "bg_tags", ""), len(sprites))[index]
            if description:
                details[key_desc] = description
            return details
    return details
