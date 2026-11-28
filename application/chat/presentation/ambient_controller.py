"""Persistent ambient overlay lifecycle, layer resolution, and directive folding."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from core.effects import parse_ambient_directive

from .effect_resolution import (
    EffectCatalog,
    EffectDirective,
    ResolvedEffectAssets,
    find_running_effect_key,
    load_runtime_effect_catalog,
    match_ambient_asset,
    normalize_effect_path,
    same_effect_asset,
)

logger = logging.getLogger(__name__)


def find_ambient_by_path(
    active: Mapping[str, Mapping[str, Any]],
    asset_path: str,
) -> tuple[str, Any | None]:
    """Find an already-running ambient entry sharing the same underlying visual path."""
    for existing_key, existing_state in active.items():
        if same_effect_asset(str(existing_state.get("path") or ""), asset_path):
            return existing_key, existing_state
    return "", None


def resolve_ambient_layer(mode: str, asset: Any) -> str:
    """Compute effective ambient z-layer (front/back) from directive mode and asset default."""
    if mode == "expose":
        return "front"
    if mode == "shelter":
        return "back"
    return (
        "front"
        if str(getattr(asset, "layer", "back") or "").strip().lower() == "front"
        else "back"
    )


def resolve_ambient_stop_key(
    keyword: str,
    matched_key: str,
    active: Mapping[str, Any],
    aliases: Mapping[str, str],
) -> str:
    """Pick the active key or alias to stop for an ``ambient-stop:`` directive."""
    stop_key = matched_key
    if not stop_key or (stop_key not in active and stop_key not in aliases):
        stop_key = find_running_effect_key(keyword, (*active, *aliases))
    return stop_key


def fold_ambient_directives(
    directives: Any, ambient_map: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Fold persisted ambient directives to the surviving active entries and layers."""
    active: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for directive in directives or ():
        parsed = parse_ambient_directive(directive)
        if parsed is None:
            continue
        mode, keyword = parsed
        if mode == "ambient-stop-all":
            active.clear()
            aliases.clear()
            continue
        if not keyword:
            continue
        matched_key, asset = match_ambient_asset(keyword, ambient_map)
        if mode == "ambient-stop":
            stop_key = resolve_ambient_stop_key(keyword, matched_key, active, aliases)
            if not stop_key:
                continue
            canonical = aliases.pop(stop_key, stop_key)
            active.pop(canonical, None)
            for alias in [k for k, target in aliases.items() if target == canonical]:
                aliases.pop(alias, None)
            continue
        if asset is None:
            continue
        resolved_path = normalize_effect_path(getattr(asset, "path", ""))
        if not resolved_path:
            continue
        key = matched_key or keyword
        canonical = aliases.get(key, key)
        current = active.get(canonical)
        if current is not None and not same_effect_asset(
            str(current.get("path") or ""), resolved_path
        ):
            active.pop(canonical, None)
            canonical = key
            current = None
        if current is None:
            existing_key, existing_state = find_ambient_by_path(active, resolved_path)
            if existing_state is not None:
                canonical = existing_key
                current = existing_state
        layer = resolve_ambient_layer(mode, asset)
        if current is not None:
            if canonical != key:
                aliases[key] = canonical
            current["layer"] = layer
            current["asset"] = asset
        else:
            aliases.pop(key, None)
            active[key] = {"asset": asset, "layer": layer, "path": resolved_path}
    return active


class StageAmbientController:
    """Own active ambient overlay instances/aliases and emit ambient lifecycle events."""

    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], None],
        media_url: Callable[[str], str],
        catalog_provider: Callable[[], EffectCatalog] = load_runtime_effect_catalog,
    ) -> None:
        self._emit = emit
        self._media_url = media_url
        self._catalog_provider = catalog_provider
        self.ambient_effects: dict[str, dict[str, str]] = {}
        self.ambient_aliases: dict[str, str] = {}

    def start_ambient_effect(
        self, keyword: str, asset: Any, layer: str = ""
    ) -> bool:
        """Start or retarget one persistent full-screen effect instance."""
        key = str(keyword or "").strip()
        path = normalize_effect_path(getattr(asset, "path", ""))
        if not key or not path:
            return False
        audio_path = normalize_effect_path(getattr(asset, "audio_path", ""))
        resolved_layer = "front" if str(layer or "").strip().lower() == "front" else "back"
        canonical = self.ambient_aliases.get(key, key)
        current = self.ambient_effects.get(canonical)
        if current is not None and not same_effect_asset(str(current.get("path") or ""), path):
            self.stop_ambient_effect(canonical)
            canonical = key
            current = None
        if current is None:
            existing_key, existing_state = find_ambient_by_path(self.ambient_effects, path)
            if existing_state is not None:
                canonical = existing_key
                current = existing_state
        if current is not None:
            if canonical != key:
                self.ambient_aliases[key] = canonical
            if current.get("layer") == resolved_layer and current.get("audioPath") == audio_path:
                return False
            current["layer"] = resolved_layer
            current["audioPath"] = audio_path
            self._emit({
                "type": "ambient.layer",
                "key": canonical,
                "layer": resolved_layer,
                "audioUrl": self._media_url(audio_path) if audio_path else "",
            })
            return True
        self.ambient_aliases.pop(key, None)
        self.ambient_effects[key] = {"path": path, "audioPath": audio_path, "layer": resolved_layer}
        self._emit({
            "type": "ambient.start",
            "key": key,
            "url": self._media_url(path),
            "audioUrl": self._media_url(audio_path) if audio_path else "",
            "layer": resolved_layer,
        })
        return True

    def stop_ambient_effect(self, keyword: str) -> bool:
        key = str(keyword or "").strip()
        canonical = self.ambient_aliases.get(key, key)
        if not key or canonical not in self.ambient_effects:
            return False
        self.ambient_effects.pop(canonical, None)
        self.ambient_aliases.pop(key, None)
        for alias in [a for a, target in self.ambient_aliases.items() if target == canonical]:
            self.ambient_aliases.pop(alias, None)
        self._emit({"type": "ambient.stop", "key": canonical})
        return True

    def stop_all_ambient_effects(self) -> None:
        if not self.ambient_effects:
            return
        self.ambient_effects.clear()
        self.ambient_aliases.clear()
        self._emit({"type": "ambient.stop-all"})

    def restore_ambient_directives(self, directives: Any) -> None:
        """Fold persisted ambient directives and emit only the surviving active effects."""
        active = fold_ambient_directives(directives, self._catalog_provider().ambient_map)
        self.stop_all_ambient_effects()
        for key, entry in active.items():
            self.start_ambient_effect(key, entry["asset"], layer=entry["layer"])

    def dispatch_start(
        self,
        raw_effect: str,
        directive: EffectDirective,
        assets: ResolvedEffectAssets,
    ) -> bool:
        if assets.ambient_asset is None:
            logger.warning(
                "chat.effect.unresolved ambient effect=%r keyword=%r",
                raw_effect,
                directive.keyword,
            )
            return False
        layer = resolve_ambient_layer(directive.mode, assets.ambient_asset)
        emitted = self.start_ambient_effect(
            assets.ambient_key or directive.keyword, assets.ambient_asset, layer=layer
        )
        if emitted:
            logger.info(
                "chat.effect.ambient effect=%r mode=%s keyword=%r layer=%r",
                raw_effect,
                directive.mode,
                directive.keyword,
                layer,
            )
        return emitted

    def dispatch_stop(
        self, directive: EffectDirective, assets: ResolvedEffectAssets
    ) -> bool:
        stop_key = resolve_ambient_stop_key(
            directive.keyword, assets.ambient_key, self.ambient_effects, self.ambient_aliases
        )
        return self.stop_ambient_effect(stop_key) if stop_key else False
