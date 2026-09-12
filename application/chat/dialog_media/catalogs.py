"""Build tagged media catalogs for one chat session."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.media.asset_tags import tag_contents

from .lookup import AssetCatalog
from .resolver import SpriteAssetResolver, asset_candidates


def build_session_asset_catalogs(
    config: Any,
    character_names: Sequence[str],
    background: Any | None,
) -> tuple[AssetCatalog, ...]:
    catalogs: list[AssetCatalog] = []
    sprite_resolver = SpriteAssetResolver()
    seen_names: set[str] = set()
    for raw_name in character_names:
        character = config.get_character_by_name(str(raw_name or ""))
        if character is None:
            continue
        name = str(getattr(character, "name", raw_name) or "").strip()
        key = name.casefold()
        if not name or key in seen_names:
            continue
        seen_names.add(key)
        catalogs.append(
            AssetCatalog(
                scope=f"sprite:{name}",
                candidates=sprite_resolver.candidates(character),
            )
        )

    if background is None:
        return tuple(catalogs)
    background_name = str(getattr(background, "name", "") or "").strip()
    sprites = list(getattr(background, "sprites", None) or [])
    catalogs.append(
        AssetCatalog(
            scope=f"scene:{background_name}",
            candidates=asset_candidates(
                sprites,
                tags=tag_contents(getattr(background, "bg_tags", ""), len(sprites)),
            ),
        )
    )
    bgm_paths = list(getattr(background, "bgm_list", None) or [])
    catalogs.append(
        AssetCatalog(
            scope=f"bgm:{background_name}",
            candidates=asset_candidates(
                bgm_paths,
                tags=tag_contents(
                    getattr(background, "bgm_tags", ""), len(bgm_paths)
                ),
                path_of=lambda path: str(path or ""),
            ),
        )
    )
    return tuple(catalogs)
