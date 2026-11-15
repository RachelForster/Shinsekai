"""Pure sprite outfit-group normalization, discovery, and index filtering."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from config.character_assets import get_character_assets
from config.schema import DEFAULT_SPRITE_GROUP, Sprite
from config.sprite_files import sprite_field


def _char_field(character: Any, key: str, default: Any = None) -> Any:
    if isinstance(character, dict):
        return character.get(key, default)
    return getattr(character, key, default)


def normalize_sprite_group(group: Any) -> str:
    """Normalize an optional group label; blank/None maps to ``DEFAULT_SPRITE_GROUP``."""
    cleaned = str(group or "").strip()
    return cleaned or DEFAULT_SPRITE_GROUP


def raw_sprite_group(sprite: Any) -> Optional[str]:
    """Return explicit non-default group label on ``sprite``, or None for default."""
    cleaned = str(sprite_field(sprite, "group", None) or "").strip()
    if not cleaned or cleaned == DEFAULT_SPRITE_GROUP:
        return None
    return cleaned


def sprite_group_of(sprite: Any) -> str:
    """Return normalized outfit group name for a ``Sprite`` or ``dict``."""
    return normalize_sprite_group(sprite_field(sprite, "group", None))


def set_sprite_group_value(sprite: Any, group: Optional[str]) -> Any:
    """Return a copy of ``sprite`` with its ``group`` set (``None`` for default)."""
    cleaned = str(group or "").strip()
    stored: Optional[str] = None if not cleaned or cleaned == DEFAULT_SPRITE_GROUP else cleaned
    if isinstance(sprite, Sprite):
        return sprite.model_copy(update={"group": stored})
    if isinstance(sprite, dict):
        updated = dict(sprite)
        if stored is None:
            updated.pop("group", None)
        else:
            updated["group"] = stored
        return updated
    return sprite


def normalize_sprite_group_list(groups: Iterable[Any] | None) -> list[str]:
    """Deduplicate and preserve order of custom outfit group names."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in groups or ():
        name = normalize_sprite_group(item)
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def list_character_sprite_groups(
    character: Any,
    *,
    avatar_type: str | None = None,
    include_empty: bool = False,
) -> list[str]:
    """List outfit groups for ``character``'s active/requested avatar bank.

    When ``include_empty=False`` (runtime lookup & prompt injection), only groups
    that actually contain at least one sprite in the bank are returned.
    When ``include_empty=True`` (editor tabs), ``DEFAULT_SPRITE_GROUP`` and any
    explicitly saved ``character.sprite_groups`` entries are included as well.
    """
    try:
        sprites = get_character_assets(character, avatar_type).sprites
    except KeyError:
        sprites = []
    present_in_order: list[str] = []
    present_set: set[str] = set()
    for sprite in sprites:
        if not sprite:
            continue
        group_name = sprite_group_of(sprite)
        if group_name not in present_set:
            present_set.add(group_name)
            present_in_order.append(group_name)

    configured_order = normalize_sprite_group_list(_char_field(character, "sprite_groups", None))

    if not include_empty:
        ordered: list[str] = [g for g in configured_order if g in present_set]
        for group_name in present_in_order:
            if group_name not in ordered:
                ordered.append(group_name)
        return ordered

    all_groups: list[str] = []
    seed = [DEFAULT_SPRITE_GROUP, *configured_order, *present_in_order]
    default_cfg = str(_char_field(character, "default_sprite_group", "") or "").strip()
    if default_cfg:
        seed.append(normalize_sprite_group(default_cfg))
    seen: set[str] = set()
    for group_name in seed:
        if group_name not in seen:
            seen.add(group_name)
            all_groups.append(group_name)
    return all_groups


def has_multiple_sprite_groups(
    character: Any,
    *,
    avatar_type: str | None = None,
) -> bool:
    """Return True iff the character bank spans 2 or more non-empty outfit groups."""
    return len(list_character_sprite_groups(character, avatar_type=avatar_type, include_empty=False)) >= 2


def allows_default_group_fallback(character: Any) -> bool:
    """Return whether empty group lookups may fall back to the default outfit group."""
    raw = _char_field(character, "fallback_to_default_group", True)
    return True if raw is None else bool(raw)


def resolve_default_sprite_group(
    character: Any,
    *,
    avatar_type: str | None = None,
) -> str:
    """Resolve the initial outfit group for ``character`` when no runtime override exists."""
    present = list_character_sprite_groups(character, avatar_type=avatar_type, include_empty=False)
    configured = str(_char_field(character, "default_sprite_group", "") or "").strip()
    if configured:
        norm = normalize_sprite_group(configured)
        if not present or norm in present:
            return norm
    if not present or DEFAULT_SPRITE_GROUP in present:
        return DEFAULT_SPRITE_GROUP
    return present[0]


def resolve_effective_sprite_group(
    character: Any,
    requested_group: str | None = None,
    *,
    avatar_type: str | None = None,
) -> str:
    """Resolve ``requested_group`` against present groups, falling back cleanly."""
    present = list_character_sprite_groups(character, avatar_type=avatar_type, include_empty=False)
    if requested_group and str(requested_group).strip():
        norm = normalize_sprite_group(requested_group)
        if not present or norm in present:
            return norm
        if allows_default_group_fallback(character):
            return resolve_default_sprite_group(character, avatar_type=avatar_type)
        return norm
    return resolve_default_sprite_group(character, avatar_type=avatar_type)


def filter_sprite_indices_for_group(
    character: Any,
    active_group: str | None = None,
    *,
    avatar_type: str | None = None,
    allow_default_fallback: bool | None = None,
) -> tuple[int, ...]:
    """Return 0-based global indices in ``assets.sprites`` belonging to ``active_group``.

    Preserves 100% original global sprite indices so ``asset_id = str(index + 1)``,
    voice bindings, and ``emotion_tags`` remain unchanged.
    """
    try:
        sprites = get_character_assets(character, avatar_type).sprites
    except KeyError:
        return ()
    if not sprites:
        return ()

    has_explicit_request = bool(active_group and str(active_group).strip())
    if not has_explicit_request and not has_multiple_sprite_groups(character, avatar_type=avatar_type):
        return tuple(range(len(sprites)))

    target_group = (
        normalize_sprite_group(active_group)
        if has_explicit_request
        else resolve_default_sprite_group(character, avatar_type=avatar_type)
    )
    matched = tuple(
        index for index, sprite in enumerate(sprites)
        if sprite_group_of(sprite) == target_group
    )
    if matched:
        return matched

    fallback_ok = (
        allows_default_group_fallback(character)
        if allow_default_fallback is None
        else bool(allow_default_fallback)
    )
    if not fallback_ok:
        return ()

    fallback_group = resolve_default_sprite_group(character, avatar_type=avatar_type)
    if fallback_group != target_group:
        fallback_matched = tuple(
            index for index, sprite in enumerate(sprites)
            if sprite_group_of(sprite) == fallback_group
        )
        if fallback_matched:
            return fallback_matched

    return ()
