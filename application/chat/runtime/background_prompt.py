"""Resolve the displayed background into data for the user prompt section."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.media.asset_tags import tag_contents


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path).replace("\\", "/")))


def current_background_context(runtime: Any) -> dict[str, str | int] | None:
    path = getattr(runtime.ui_update_manager, "current_background_path", None)
    if path is not None and not isinstance(path, (str, Path)):
        return None
    if not path:
        return None
    else:
        details = {"图片": Path(str(path).replace("\\", "/")).name}
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
                details.update({"背景组": str(background.name), "背景编号": index + 1})
                description = tag_contents(getattr(background, "bg_tags", ""), len(sprites))[index]
                if description:
                    details["描述"] = description
                return details
    return details
