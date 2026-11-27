"""Legacy-compatible Novel Theater casting map reconstruction helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from application.session_behavior.casting import CastBinding, CastingMap


def casting_map_from_novel_state(state: Mapping[str, Any]) -> CastingMap:
    """Build a ``CastingMap`` from persisted state, hydrating missing display names from ``castEntries``."""
    raw_casting = state.get("casting")
    casting = (
        CastingMap.from_dict(raw_casting)
        if isinstance(raw_casting, Mapping)
        else CastingMap()
    )
    raw_entries = state.get("castEntries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
        return casting
    if not raw_entries:
        return casting
    if casting.bindings and all(b.display_name for b in casting.bindings):
        return casting

    legacy_revealed_by_target: dict[str, bool] = {}
    for binding in casting.bindings:
        legacy_revealed_by_target.setdefault(binding.character_name, binding.revealed)

    synthesized: list[CastBinding] = []
    for item in raw_entries:
        if not isinstance(item, Mapping):
            continue
        target = str(
            item.get("targetCharacter") or item.get("target_character") or ""
        ).strip()
        if not target:
            continue
        source_name = (
            str(item.get("sourceName") or item.get("source_name") or target).strip()
            or target
        )
        raw_aliases = item.get("aliases") or ()
        aliases_seq = raw_aliases if isinstance(raw_aliases, (list, tuple)) else ()
        merged_aliases = tuple(
            dict.fromkeys(
                clean
                for raw_alias in (source_name, *aliases_seq)
                if (clean := str(raw_alias or "").strip()) and clean != target
            )
        )
        role = str(item.get("role") or "supporting").strip() or "supporting"
        silhouette = bool(
            item.get(
                "silhouetteUntilRevealed",
                item.get("silhouette_until_revealed", False),
            )
        )
        revealed = legacy_revealed_by_target.get(target, not silhouette)
        synthesized.append(
            CastBinding(
                character_name=target,
                display_name=source_name,
                aliases=merged_aliases,
                role=role,
                silhouette_until_revealed=silhouette,
                revealed=revealed,
            )
        )
    return CastingMap(synthesized) if synthesized else casting


__all__ = ["casting_map_from_novel_state"]
