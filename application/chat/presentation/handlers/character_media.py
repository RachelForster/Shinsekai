"""Character dialog media handler with optional CastingMap NPC passthrough."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
import sys
import traceback
from typing import Any
import uuid

from application.chat.dialog_media import (
    AssetIdMatch,
    AssetLookupRequest,
    AssetLookupResult,
    AssetLookupStrategy,
    DefaultTtsGenerationStrategy,
    MessageAssetIdLookupStrategy,
    ResolvedSpriteAsset,
    SpriteAssetResolver,
    TtsGenerationRequest,
    TtsGenerationStrategy,
)
from application.chat.voice_archive import VoiceArchive
from application.runtime.context import get_app_runtime as _context_get_app_runtime
from config.schema import (
    resolve_character_by_prompt_name,
    resolve_character_prompt_name,
)
from config.sprite_groups import (
    allows_default_group_fallback,
    has_multiple_sprite_groups,
    resolve_default_sprite_group,
)
from i18n import tr as tr_i18n
from sdk.handlers import MessageHandler
from sdk.messages import LLMDialogMessage, PresentationMessage

get_app_runtime = _context_get_app_runtime


def _resolve_app_runtime() -> Any:
    facade = sys.modules.get("application.chat.presentation.handlers.dialog_media")
    facade_getter = getattr(facade, "get_app_runtime", None) if facade is not None else None
    if callable(facade_getter) and facade_getter is not _context_get_app_runtime:
        return facade_getter()
    return get_app_runtime()


def _post_media_busy(text: str) -> None:
    try:
        _resolve_app_runtime().ui_update_manager.post_busy_bar(text, 0.0)
    except Exception:
        pass


def _hide_media_busy() -> None:
    try:
        _resolve_app_runtime().ui_update_manager.hide_busy_bar()
    except Exception:
        pass


def _cc():
    return _resolve_app_runtime().opencc


def _refresh_config(rt) -> None:
    """Refresh the child-process snapshot before resolving editable catalogs."""
    try:
        refresh = getattr(rt.config, "refresh_media_catalogs", None)
        if callable(refresh):
            refresh()
        else:
            rt.config.reload()
    except Exception:
        pass


def lookup_request(
    msg: LLMDialogMessage,
    *,
    scope: str,
    candidates,
    previous_asset_id: str = "",
) -> AssetLookupRequest:
    return AssetLookupRequest(
        scope=scope,
        candidates=tuple(candidates),
        explicit_asset_id=str(msg.asset_id if msg.asset_id is not None else "-1"),
        vibe=str(msg.vibe or ""),
        previous_asset_id=previous_asset_id,
    )


class CharacterMediaHandler(MessageHandler):
    """Handle regular character dialogue and optional CastingMap unbound NPCs."""

    def __init__(
        self,
        asset_lookup_strategy: AssetLookupStrategy | None = None,
        tts_generation_strategy: TtsGenerationStrategy | None = None,
        sprite_resolver: SpriteAssetResolver | None = None,
        casting_map_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.asset_lookup_strategy = (
            MessageAssetIdLookupStrategy()
            if asset_lookup_strategy is None
            else asset_lookup_strategy
        )
        self.sprite_resolver = sprite_resolver or SpriteAssetResolver()
        self.tts_generation_strategy = (
            DefaultTtsGenerationStrategy()
            if tts_generation_strategy is None
            else tts_generation_strategy
        )
        self.casting_map_provider = casting_map_provider
        self._last_sprite_by_character: dict[str, str] = {}
        self._sprite_catalog_by_character: dict[str, tuple[tuple[str, str, str], ...]] = {}

    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return True

    @staticmethod
    def _audio_segments(audio_paths: Iterable[str]) -> Iterator[tuple[str, bool]]:
        iterator = iter(audio_paths)
        try:
            current = next(iterator)
        except StopIteration:
            yield "", True
            return

        for following in iterator:
            yield current, False
            current = following
        yield current, True

    @staticmethod
    def _presentation_messages(
        *,
        character_name: str,
        message: LLMDialogMessage,
        sprite: ResolvedSpriteAsset,
        audio_paths: Iterable[str],
        voice_id: str = "",
    ) -> Iterator[PresentationMessage]:
        speech = message.text or ""
        if sprite.voice_type == "preset" and sprite.voice_path:
            speech = sprite.voice_text or speech

        for index, (audio_path, is_final) in enumerate(
            CharacterMediaHandler._audio_segments(audio_paths)
        ):
            first = index == 0
            yield PresentationMessage(
                audio_path=audio_path or "",
                voice_id=voice_id,
                dialog_id=message.dialog_id,
                name=character_name,
                text=speech if first else "",
                asset_id=sprite.asset_id,
                effect=(message.effect or "") if (
                    is_final if str(message.effect or "").strip().upper() == "LEAVE" else first
                ) else "",
                is_system_message=False,
                is_final_segment=is_final,
                timeout=None if first else 0,
            )

    def _emit_unbound_npc_dialog(self, rt: Any, *, raw_name: str, msg: LLMDialogMessage, replaying: bool) -> None:
        if replaying:
            return
        rt.presentation_queue.put(
            PresentationMessage(
                audio_path="",
                voice_id="",
                dialog_id=msg.dialog_id,
                name=raw_name,
                text=msg.text or "",
                asset_id="-1",
                effect=msg.effect or "",
                is_system_message=False,
                is_final_segment=True,
                timeout=None,
            )
        )

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = _resolve_app_runtime()
        raw_name = str(msg.name or "")
        replaying = bool(getattr(msg, "_presentation_replay", False))
        _refresh_config(rt)
        cc = _cc()

        lookup_name = raw_name
        casting_map = (
            self.casting_map_provider() if callable(self.casting_map_provider) else None
        )
        if casting_map is not None:
            binding = casting_map.resolve(raw_name, cc=cc)
            if binding is None:
                resolved_char = resolve_character_by_prompt_name(rt.config, raw_name)
                if resolved_char is None:
                    resolved_char = resolve_character_by_prompt_name(
                        rt.config, cc.convert(raw_name)
                    )
                if resolved_char is not None:
                    resolved_name = getattr(resolved_char, "name", None)
                    if isinstance(resolved_name, str) and resolved_name.strip():
                        binding = casting_map.resolve(resolved_name, cc=cc)
            if binding is None:
                self._emit_unbound_npc_dialog(
                    rt, raw_name=raw_name, msg=msg, replaying=replaying
                )
                return
            lookup_name = binding.character_name

        character_config = resolve_character_by_prompt_name(rt.config, lookup_name)
        if character_config is None:
            character_config = resolve_character_by_prompt_name(
                rt.config, cc.convert(lookup_name)
            )
        if character_config is None:
            raise ValueError(f"未找到角色配置: {lookup_name}")
        raw_char_name = getattr(character_config, "name", None)
        name_s = (
            raw_char_name.strip()
            if isinstance(raw_char_name, str) and raw_char_name.strip()
            else lookup_name
        )
        cfg_chars = getattr(getattr(rt.config, "config", None), "characters", ()) or ()
        all_char_names = [
            cname
            for c in cfg_chars
            if isinstance((cname := getattr(c, "name", None)), str) and cname.strip()
        ]
        display_name = resolve_character_prompt_name(
            character_config, name_s, colliding_names=all_char_names
        )

        if has_multiple_sprite_groups(character_config):
            outfit_controller = getattr(rt, "outfit_controller", None)
            if outfit_controller is not None and not replaying:
                outfit_switched, active_group = (
                    outfit_controller.apply_streamed_outfit_switch(
                        character_config,
                        getattr(msg, "outfit", ""),
                    )
                )
                if not active_group:
                    active_group = (
                        outfit_controller.active_group_for(character_config)
                        or resolve_default_sprite_group(character_config)
                    )
            elif outfit_controller is not None:
                outfit_switched = False
                active_group = (
                    outfit_controller.active_group_for(character_config)
                    or resolve_default_sprite_group(character_config)
                )
            else:
                outfit_switched = False
                active_group = resolve_default_sprite_group(character_config)
            candidates_for_group = getattr(
                self.sprite_resolver, "candidates_for_group", None
            )
            candidates = (
                candidates_for_group(character_config, active_group)
                if callable(candidates_for_group)
                else self.sprite_resolver.candidates(character_config)
            )
            sprite_scope = f"sprite:{name_s}:{active_group}"
        else:
            outfit_switched = False
            active_group = None
            candidates = self.sprite_resolver.candidates(character_config)
            sprite_scope = f"sprite:{name_s}"

        current_catalog = tuple(
            (candidate.asset_id, candidate.path, candidate.tags)
            for candidate in candidates
        )
        if self._sprite_catalog_by_character.get(name_s) != current_catalog:
            self._last_sprite_by_character.pop(name_s, None)
            self._sprite_catalog_by_character[name_s] = current_catalog
        lookup_result = self.asset_lookup_strategy.lookup(
            lookup_request(
                msg,
                scope=sprite_scope,
                candidates=candidates,
                previous_asset_id=self._last_sprite_by_character.get(name_s, ""),
            )
        )
        sprite = self.sprite_resolver.resolve(
            character_config,
            candidates,
            lookup_result,
        )
        default_group = resolve_default_sprite_group(character_config) if active_group is not None else None
        if (
            not sprite.found
            and not replaying
            and default_group is not None
            and active_group != default_group
            and str(msg.vibe or "").strip()
            and allows_default_group_fallback(character_config)
        ):
            candidates_for_group = getattr(
                self.sprite_resolver, "candidates_for_group", None
            )
            default_candidates = (
                candidates_for_group(character_config, default_group)
                if callable(candidates_for_group)
                else ()
            )
            if default_candidates:
                fb_result = self.asset_lookup_strategy.lookup(
                    lookup_request(
                        msg,
                        scope=f"sprite:{name_s}:{default_group}",
                        candidates=default_candidates,
                        previous_asset_id=self._last_sprite_by_character.get(
                            name_s, ""
                        ),
                    )
                )
                sprite = self.sprite_resolver.resolve(
                    character_config,
                    default_candidates,
                    fb_result,
                )
        # The saved group can differ from the group that supplied the old sprite ID.
        if (
            not sprite.found and candidates
            and (outfit_switched or (replaying and active_group is not None))
        ):
            sprite = self.sprite_resolver.resolve(
                character_config,
                candidates,
                AssetLookupResult(
                    matches=(AssetIdMatch(asset_id=candidates[0].asset_id),)
                ),
            )
        if sprite.found:
            self._last_sprite_by_character[name_s] = sprite.asset_id
        if replaying:
            rt.presentation_queue.put(
                PresentationMessage(
                    audio_path="",
                    name=display_name,
                    text="",
                    asset_id=sprite.asset_id,
                    effect="",
                    is_system_message=False,
                    timeout=0,
                )
            )
            return
        is_player = name_s == str(getattr(rt, "player_character", "") or "")
        # A portrait's fixed recording must not replace a newly written reply.
        speech_sprite = (
            replace(sprite, voice_type="reference")
            if is_player and sprite.voice_type == "preset" else sprite
        )
        generation_request = TtsGenerationRequest(
            runtime=rt,
            character=character_config,
            character_name=name_s,
            message=msg,
            sprite=speech_sprite,
        )
        player_silent = is_player and (
            not bool(getattr(rt, "read_player_speech", False))
            or not (str(msg.text or "").strip() or str(msg.translate or "").strip())
        )
        show_busy = rt.tts_manager is not None and not player_silent
        if show_busy:
            _post_media_busy(tr_i18n("desktop.tts_busy_synthesizing", name=display_name))
        try:
            audio_paths = (
                ("",) if player_silent
                else self.tts_generation_strategy.generate(generation_request)
            )
            archive = getattr(rt.ui_update_manager, "voice_archive", None)
            if not isinstance(archive, VoiceArchive):
                archive = None
            voice_id = uuid.uuid4().hex if archive is not None else ""

            def track_audio() -> Iterator[str]:
                all_recorded = True
                for path in audio_paths:
                    if archive is not None and path:
                        try:
                            all_recorded = archive.record(
                                voice_id, path, dialog_id=msg.dialog_id,
                            ) and all_recorded
                        except OSError:
                            all_recorded = False
                            traceback.print_exc()
                    elif archive is not None:
                        all_recorded = False
                    yield path
                if archive is not None and all_recorded:
                    try:
                        archive.complete(voice_id)
                    except OSError:
                        traceback.print_exc()
                    else:
                        rt.ui_update_manager.sync_history_entries()

            for output in self._presentation_messages(
                character_name=display_name,
                message=msg,
                sprite=speech_sprite,
                audio_paths=track_audio(),
                voice_id=voice_id,
            ):
                rt.presentation_queue.put(output)
        finally:
            if show_busy:
                _hide_media_busy()


__all__ = ["CharacterMediaHandler", "lookup_request"]
