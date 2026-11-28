"""Pure directive parsing and keyword asset resolution for stage effects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.effects import match_effect_label, parse_ambient_directive
from core.paths import resource_path

SOUND_EFFECTS_PATH = {
    "DISAPPOINTED": "./assets/system/sound/disappointed.wav",
    "SHOCKED": "./assets/system/sound/shocked.wav",
    "ATTENTION": "./assets/system/sound/attention.wav",
}

IMAGE_EFFECT_DURATION_MS = 8_800


@dataclass(frozen=True, slots=True)
class EffectDirective:
    """Normalized stage effect directive parsed from a presenter command string."""

    mode: str
    keyword: str
    timing: str = ""


@dataclass(frozen=True, slots=True)
class EffectCatalog:
    """Immutable view of runtime effect asset keyword tables."""

    audio_map: Mapping[str, str] = field(default_factory=dict)
    image_map: Mapping[str, Any] = field(default_factory=dict)
    ambient_map: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolvedEffectAssets:
    """Matched audio, image, and ambient effect candidates for a keyword."""

    audio_key: str = ""
    audio_path: str = ""
    image_key: str = ""
    image_path: str = ""
    ambient_key: str = ""
    ambient_asset: Any = None


def normalize_effect_path(raw_path: str) -> str:
    """Resolve absolute asset paths through ``resource_path`` while keeping relative paths."""
    cleaned = str(raw_path or "").strip()
    if not cleaned:
        return ""
    return str(resource_path(cleaned)) if Path(cleaned).is_absolute() else cleaned


def same_effect_asset(left: str, right: str) -> bool:
    """Compare normalized file paths to identify aliased loop or ambient instances."""
    if not left or not right:
        return False
    try:
        return os.path.normcase(os.path.normpath(left)) == os.path.normcase(
            os.path.normpath(right)
        )
    except (TypeError, ValueError):
        return left == right


def find_running_effect_key(query: str, keys: Any) -> str:
    """Resolve a stop label against the effects that are actually running."""
    candidates = tuple(str(key) for key in keys if str(key or "").strip())
    normalized_query = str(query or "").strip().casefold()
    for key in candidates:
        if key.strip().casefold() == normalized_query:
            return key
    matched = match_effect_label(query, candidates)
    return matched or ""


def match_ambient_asset(
    keyword: str,
    ambient_map: Mapping[str, Any],
    *,
    allow_fuzzy: bool = True,
) -> tuple[str, Any | None]:
    """Resolve an ambient effect keyword against configured entries."""
    keyword_key = str(keyword or "").strip().casefold()
    if keyword_key in ambient_map:
        return keyword_key, ambient_map[keyword_key]
    if allow_fuzzy:
        matched = match_effect_label(keyword, tuple(ambient_map))
        if matched is not None:
            return matched, ambient_map[matched]
    return "", None


def parse_effect_directive(effect: str) -> EffectDirective | None:
    """Parse ``LEAVE``, ambient prefixes, loop/stop controls, and before/after timing."""
    raw = str(effect or "").strip()
    if not raw:
        return None
    if raw.upper() == "LEAVE":
        return EffectDirective(mode="leave", keyword="")

    ambient_directive = parse_ambient_directive(raw)
    if ambient_directive is not None:
        mode, body = ambient_directive
        return EffectDirective(mode=mode, keyword=body.strip())

    if raw.startswith("loop:"):
        return EffectDirective(mode="loop", keyword=raw[5:].strip())
    if raw.startswith("stop:"):
        return EffectDirective(mode="stop", keyword=raw[5:].strip())

    timing = "before"
    if raw.startswith("before:"):
        raw = raw[7:]
    elif raw.startswith("after:"):
        timing = "after"
        raw = raw[6:]
    return EffectDirective(mode="once", keyword=raw.strip(), timing=timing)


def should_skip_for_timing(directive: EffectDirective, *, after_dialog: bool) -> bool:
    """Return True when a one-shot directive belongs to the other phase of dialog delivery."""
    if directive.mode != "once":
        return False
    return (directive.timing == "before" and after_dialog) or (
        directive.timing == "after" and not after_dialog
    )


def load_runtime_effect_catalog() -> EffectCatalog:
    """Read configured effect keyword maps lazily from the active application runtime."""
    try:
        from application.runtime.context import get_app_runtime

        runtime = get_app_runtime()
        return EffectCatalog(
            audio_map=getattr(runtime, "effect_keyword_map", {}) or {},
            image_map=getattr(runtime, "effect_image_keyword_map", {}) or {},
            ambient_map=getattr(runtime, "ambient_effect_keyword_map", {}) or {},
        )
    except Exception:
        return EffectCatalog()


def resolve_effect_assets(keyword: str, catalog: EffectCatalog) -> ResolvedEffectAssets:
    """Resolve audio, image, and ambient assets with exact-match priority over fuzzy fallback."""
    audio_path = str(SOUND_EFFECTS_PATH.get(keyword.upper()) or "").strip()
    audio_key = keyword if audio_path else ""
    keyword_key = keyword.casefold()
    exact_audio = bool(audio_path) or keyword_key in catalog.audio_map
    exact_image = keyword_key in catalog.image_map
    exact_ambient = keyword_key in catalog.ambient_map
    has_exact_label = exact_audio or exact_image or exact_ambient

    if not audio_path:
        if keyword_key in catalog.audio_map:
            audio_key = keyword_key
            audio_path = str(catalog.audio_map[keyword_key] or "").strip()
        elif not has_exact_label:
            matched_audio = match_effect_label(keyword, tuple(catalog.audio_map))
            if matched_audio is not None:
                audio_key = matched_audio
                audio_path = str(catalog.audio_map[matched_audio] or "").strip()

    image_key = ""
    image_path = ""
    image_audio_path = ""
    image = catalog.image_map.get(keyword_key) if exact_image else None
    if image is None and not has_exact_label:
        matched_image = match_effect_label(keyword, tuple(catalog.image_map))
        if matched_image is not None:
            image_key = matched_image
            image = catalog.image_map[matched_image]
    if exact_image:
        image_key = keyword_key
    if image is not None:
        image_path = image.image_path
        image_audio_path = image.audio_path

    ambient_key, ambient_asset = match_ambient_asset(
        keyword,
        catalog.ambient_map,
        allow_fuzzy=not has_exact_label,
    )

    if image_audio_path:
        audio_path = image_audio_path

    return ResolvedEffectAssets(
        audio_key=audio_key,
        audio_path=audio_path,
        image_key=image_key,
        image_path=image_path,
        ambient_key=ambient_key,
        ambient_asset=ambient_asset,
    )
