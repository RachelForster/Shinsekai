"""Stage sound, image, loop playback, and effect directive dispatch controller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict

from core.effects import effect_modes

from .ambient_controller import StageAmbientController
from .effect_resolution import (
    IMAGE_EFFECT_DURATION_MS,
    EffectCatalog,
    EffectDirective,
    ResolvedEffectAssets,
    find_running_effect_key,
    load_runtime_effect_catalog,
    normalize_effect_path,
    parse_effect_directive,
    resolve_effect_assets,
    same_effect_asset,
    should_skip_for_timing,
)

logger = logging.getLogger(__name__)


class StageEffectController:
    """Own loop effect state and dispatch resolved directives across audio/image/ambient."""

    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], None],
        media_url: Callable[[str], str],
        remove_sprite: Callable[[str], None],
        ambient: StageAmbientController | None = None,
        catalog_provider: Callable[[], EffectCatalog] = load_runtime_effect_catalog,
    ) -> None:
        self._emit = emit
        self._media_url = media_url
        self._remove_sprite = remove_sprite
        self._catalog_provider = catalog_provider
        self._ambient = (
            ambient
            if ambient is not None
            else StageAmbientController(
                emit=emit,
                media_url=media_url,
                catalog_provider=catalog_provider,
            )
        )
        self.looping_effects: dict[str, str] = {}

    def play_sound_effect(self, sound_effect_path: str) -> None:
        path = normalize_effect_path(sound_effect_path)
        if not path:
            return
        self._emit({"type": "effect.play", "url": self._media_url(path)})

    def show_image_effect(self, keyword: str, image_effect_path: str) -> None:
        path = normalize_effect_path(image_effect_path)
        if not path:
            return
        self._emit({
            "type": "effect.image.show",
            "url": self._media_url(path),
            "label": str(keyword or "").strip(),
            "durationMs": IMAGE_EFFECT_DURATION_MS,
        })

    def start_loop_effect(self, keyword: str, audio_path: str) -> None:
        key = str(keyword or "").strip()
        path = normalize_effect_path(audio_path)
        if not key or not path or key in self.looping_effects:
            return
        self.looping_effects[key] = path
        self._emit({"type": "effect.loop.start", "key": key, "url": self._media_url(path)})

    def stop_loop_effect(self, keyword: str) -> None:
        key = str(keyword or "").strip()
        if not key or key not in self.looping_effects:
            return
        path = self.looping_effects.pop(key, None)
        # Aliases share one asset-level loop instance. Drop every alias with the
        # same asset so a stale snapshot key cannot revive the sound on resume.
        removed = [key]
        if path:
            for alias, _alias_path in [
                (existing, existing_path)
                for existing, existing_path in self.looping_effects.items()
                if same_effect_asset(existing_path, path)
            ]:
                self.looping_effects.pop(alias, None)
                removed.append(alias)
        # Emit a stop for every removed key: the snapshot reducers and the
        # frontend state only drop the key named by the event, so a missing
        # alias would survive in ``loopingEffects`` and restart after a
        # polling recovery or WebSocket reconnect.
        for removed_key in removed:
            self._emit({"type": "effect.loop.stop", "key": removed_key})

    def stop_all_loop_effects(self) -> None:
        if not self.looping_effects:
            return
        self.looping_effects.clear()
        self._emit({"type": "effect.loop.stop-all"})

    @staticmethod
    def _log_emitted(raw_effect: str, directive: EffectDirective, audio_path: str) -> None:
        logger.info(
            "chat.effect.emitted effect=%r mode=%s keyword=%r path=%r",
            raw_effect,
            directive.mode,
            directive.keyword,
            audio_path,
        )

    def _dispatch_loop(
        self,
        raw_effect: str,
        directive: EffectDirective,
        assets: ResolvedEffectAssets,
    ) -> bool:
        if not assets.audio_path and not assets.image_path:
            logger.warning(
                "chat.effect.unresolved effect=%r keyword=%r", raw_effect, directive.keyword
            )
            return False
        if "loop" not in effect_modes(has_image=bool(assets.image_path)):
            return False
        loop_key = assets.audio_key or directive.keyword
        self.start_loop_effect(loop_key, assets.audio_path)
        emitted = loop_key in self.looping_effects
        if emitted:
            self._log_emitted(raw_effect, directive, assets.audio_path)
        return emitted

    def _dispatch_stop(
        self,
        raw_effect: str,
        directive: EffectDirective,
        assets: ResolvedEffectAssets,
    ) -> bool:
        stop_key = assets.audio_key
        if not stop_key or stop_key not in self.looping_effects:
            stop_key = find_running_effect_key(directive.keyword, self.looping_effects)
        if not stop_key:
            return False
        self.stop_loop_effect(stop_key)
        self._log_emitted(raw_effect, directive, assets.audio_path)
        return True

    def _dispatch_once(
        self,
        raw_effect: str,
        directive: EffectDirective,
        assets: ResolvedEffectAssets,
    ) -> bool:
        if not assets.audio_path and not assets.image_path:
            logger.warning(
                "chat.effect.unresolved effect=%r keyword=%r", raw_effect, directive.keyword
            )
            return False
        if assets.audio_path:
            self.play_sound_effect(assets.audio_path)
        if assets.image_path:
            self.show_image_effect(assets.image_key or directive.keyword, assets.image_path)
        emitted = bool(assets.audio_path or assets.image_path)
        if emitted:
            self._log_emitted(raw_effect, directive, assets.audio_path)
        return emitted

    def resolve_effect(
        self, effect: str, args: Dict[str, Any], after_dialog: bool = False
    ) -> bool:
        """Resolve an effect directive string and emit the matching stage events."""
        directive = parse_effect_directive(effect)
        if directive is None:
            return False
        if directive.mode == "leave":
            if after_dialog:
                self._remove_sprite(str(args.get("character_name") or ""))
            return True
        if directive.mode == "ambient-stop-all":
            self._ambient.stop_all_ambient_effects()
            return True
        if should_skip_for_timing(directive, after_dialog=after_dialog):
            return True
        if not directive.keyword:
            return False

        assets = resolve_effect_assets(directive.keyword, self._catalog_provider())
        handlers = {
            "ambient": self._ambient.dispatch_start,
            "shelter": self._ambient.dispatch_start,
            "expose": self._ambient.dispatch_start,
            "ambient-stop": lambda _e, d, a: self._ambient.dispatch_stop(d, a),
            "loop": self._dispatch_loop,
            "stop": self._dispatch_stop,
            "once": self._dispatch_once,
        }
        return handlers[directive.mode](effect, directive, assets)
