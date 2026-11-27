"""Novel Theater casting normalization helpers and legacy-state reconstruction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from application.session_behavior.casting import CastBinding, CastingMap

NOVEL_NAME_MODE_ACTOR = "actor"
NOVEL_NAME_MODE_STORY = "story"
DEFAULT_NOVEL_NAME_MODE = NOVEL_NAME_MODE_ACTOR


def normalize_novel_name_mode(
    value: Any,
    *,
    default: str = DEFAULT_NOVEL_NAME_MODE,
) -> str:
    """Normalize a requested character-naming mode to ``actor`` or ``story``."""
    raw = str(value or "").strip().lower()
    if raw == NOVEL_NAME_MODE_ACTOR:
        return NOVEL_NAME_MODE_ACTOR
    if raw == NOVEL_NAME_MODE_STORY:
        return NOVEL_NAME_MODE_STORY
    return NOVEL_NAME_MODE_ACTOR if default == NOVEL_NAME_MODE_ACTOR else NOVEL_NAME_MODE_STORY


def count_cast_targets(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count non-empty local character bindings (case-insensitive) to detect many-to-one sharing."""
    counts: dict[str, int] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        target = str(
            item.get("targetCharacter") or item.get("target_character") or ""
        ).strip()
        if not target:
            continue
        key = target.casefold()
        counts[key] = counts.get(key, 0) + 1
    return counts


def effective_cast_display_name(
    source_name: str,
    target_character: str,
    *,
    name_mode: str,
    target_counts: Mapping[str, int],
) -> str:
    """Resolve stage/prompt display name: 1-to-1 actor name in ``actor`` mode, else novel name."""
    clean_source = str(source_name or "").strip()
    clean_target = str(target_character or "").strip()
    if (
        name_mode == NOVEL_NAME_MODE_ACTOR
        and clean_target
        and target_counts.get(clean_target.casefold(), 0) == 1
    ):
        return clean_target
    return clean_source or clean_target


def novel_prompt_character_entries(
    payload: Mapping[str, Any],
    characters: Sequence[str],
) -> list[tuple[str, str]]:
    """Build ``(prompt_display_name, local_actor_name)`` pairs for system prompt generation."""
    pairs: list[tuple[str, str]] = []
    seen_display: set[str] = set()
    name_mode = normalize_novel_name_mode(
        payload.get("nameMode"),
        default=NOVEL_NAME_MODE_STORY,
    )
    raw_entries = payload.get("castEntries")
    if isinstance(raw_entries, Sequence) and not isinstance(raw_entries, (str, bytes)):
        target_counts = count_cast_targets(raw_entries)
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
            display = effective_cast_display_name(
                source_name,
                target,
                name_mode=name_mode,
                target_counts=target_counts,
            )
            if display not in seen_display:
                seen_display.add(display)
                pairs.append((display, target))
        if pairs:
            return pairs
    raw_casting = payload.get("casting")
    if isinstance(raw_casting, Mapping):
        raw_bindings = raw_casting.get("bindings")
        if isinstance(raw_bindings, Sequence) and not isinstance(raw_bindings, (str, bytes)):
            for item in raw_bindings:
                if not isinstance(item, Mapping):
                    continue
                target = str(item.get("characterName") or "").strip()
                if not target:
                    continue
                display = str(item.get("displayName") or target).strip() or target
                if display not in seen_display:
                    seen_display.add(display)
                    pairs.append((display, target))
            if pairs:
                return pairs
    return [(name, name) for name in characters if str(name or "").strip()]


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

    name_mode = normalize_novel_name_mode(
        state.get("nameMode"),
        default=NOVEL_NAME_MODE_STORY,
    )
    target_counts = count_cast_targets(raw_entries)
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
        display_name = effective_cast_display_name(
            source_name,
            target,
            name_mode=name_mode,
            target_counts=target_counts,
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
                display_name=display_name,
                aliases=merged_aliases,
                role=role,
                silhouette_until_revealed=silhouette,
                revealed=revealed,
            )
        )
    return CastingMap(synthesized) if synthesized else casting


__all__ = [
    "DEFAULT_NOVEL_NAME_MODE",
    "NOVEL_NAME_MODE_ACTOR",
    "NOVEL_NAME_MODE_STORY",
    "casting_map_from_novel_state",
    "count_cast_targets",
    "effective_cast_display_name",
    "normalize_novel_name_mode",
    "novel_prompt_character_entries",
]
