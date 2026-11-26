"""
dialog media worker 用 LLM dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :mod:`application.runtime.context` 取得，不引用 worker 类型。
"""

from __future__ import annotations

from collections.abc import Callable
import traceback
from typing import Any, List

from application.chat.dialog_media import (
    AssetLookupStrategy,
    AssetResolver,
    MessageAssetIdLookupStrategy,
    SpriteAssetResolver,
    TtsGenerationStrategy,
    asset_candidates,
)
from application.chat.presentation.handlers.character_media import (
    CharacterMediaHandler,
    _cc,
    _hide_media_busy,
    _post_media_busy,
    _refresh_config,
    lookup_request as _lookup_request,
)
from application.runtime.context import emit_presentation_message, get_app_runtime
from core.media.asset_tags import tag_contents
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_dialog,
    match_scene_dialog,
    match_system_dialog,
    normalize_character_name,
)
from core.messaging.stage_effects import normalize_scene_transition
from i18n import tr as tr_i18n
from sdk.handlers import MessageHandler
from sdk.messages import LLMDialogMessage


class ChainOfThoughtMediaHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cot_dialog(_cc(), msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        disp_name = _cc().convert(normalize_character_name(msg.name))
        emit_presentation_message(
            disp_name,
            msg.text or "",
            str(msg.asset_id if msg.asset_id is not None else "-1"),
            "",
            is_system_message=True,
            effect=msg.effect or "",
        )


class SceneMediaHandler(MessageHandler):
    def __init__(
        self,
        asset_lookup_strategy: AssetLookupStrategy | None = None,
        asset_resolver: AssetResolver | None = None,
    ) -> None:
        self.asset_lookup_strategy = (
            asset_lookup_strategy or MessageAssetIdLookupStrategy()
        )
        self.asset_resolver = asset_resolver or AssetResolver()

    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_scene_dialog(_cc(), msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        _refresh_config(rt)
        background_name = str(getattr(rt.background, "name", "") or "")
        refreshed_background = rt.config.get_background_by_name(background_name)
        background = (
            refreshed_background
            if isinstance(getattr(refreshed_background, "name", None), str)
            else rt.background
        )
        sprites = list(getattr(background, "sprites", None) or [])
        if hasattr(rt.ui_update_manager, "bg_group"):
            rt.ui_update_manager.bg_group = sprites
        tags = tag_contents(getattr(background, "bg_tags", ""), len(sprites))
        candidates = asset_candidates(sprites, tags=tags)
        result = self.asset_lookup_strategy.lookup(
            _lookup_request(
                msg,
                scope=f"scene:{getattr(background, 'name', '')}",
                candidates=candidates,
            )
        )
        resolved = self.asset_resolver.resolve(candidates, result)
        if not resolved.found:
            return
        emit_presentation_message(
            _cc().convert(normalize_character_name(msg.name)),
            msg.text,
            resolved.asset_id,
            "",
            is_system_message=True,
            effect=msg.effect,
            transition=normalize_scene_transition(getattr(msg, "transition", "")),
        )


class SystemDialogMediaHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_system_dialog(_cc(), msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        disp_name = _cc().convert(normalize_character_name(msg.name))
        emit_presentation_message(
            disp_name,
            msg.text,
            str(msg.asset_id),
            "",
            is_system_message=True,
            effect=msg.effect,
        )


class BgmMediaHandler(MessageHandler):
    def __init__(
        self,
        asset_lookup_strategy: AssetLookupStrategy | None = None,
        asset_resolver: AssetResolver | None = None,
    ) -> None:
        self.asset_lookup_strategy = (
            asset_lookup_strategy or MessageAssetIdLookupStrategy()
        )
        self.asset_resolver = asset_resolver or AssetResolver()

    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_bgm_name(msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        _refresh_config(rt)
        background_name = str(getattr(rt.background, "name", "") or "")
        refreshed_background = rt.config.get_background_by_name(background_name)
        background = (
            refreshed_background
            if isinstance(getattr(refreshed_background, "name", None), str)
            else rt.background
        )
        paths = list(getattr(background, "bgm_list", None) or rt.bgm_list or [])
        tags = tag_contents(getattr(background, "bgm_tags", ""), len(paths))
        candidates = asset_candidates(
            paths,
            tags=tags,
            path_of=lambda path: str(path or ""),
        )
        result = self.asset_lookup_strategy.lookup(
            _lookup_request(
                msg,
                scope=f"bgm:{getattr(background, 'name', '')}",
                candidates=candidates,
            )
        )
        resolved = self.asset_resolver.resolve(candidates, result)
        if not resolved.found:
            return
        emit_presentation_message(
            "bgm",
            "",
            resolved.asset_id,
            resolved.path,
            is_system_message=True,
            effect=msg.effect,
        )


class CgMediaHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cg_name(msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        _post_media_busy(tr_i18n("desktop.tts_busy_cg"))
        try:
            cg_path = get_app_runtime().t2i_manager.t2i(
                prompt=msg.text, prompt_processor=None
            )
            emit_presentation_message(
                msg.name, msg.text, "-1", cg_path, is_system_message=True
            )
        except Exception as e:
            print(f"生成CG失败，{e}")
            traceback.print_exc()
        finally:
            _hide_media_busy()


def get_dialog_media_handlers(
    *,
    asset_lookup_strategy: AssetLookupStrategy | None = None,
    sprite_resolver: SpriteAssetResolver | None = None,
    tts_generation_strategy: TtsGenerationStrategy | None = None,
    casting_map_provider: Callable[[], Any] | None = None,
) -> List[MessageHandler]:
    lookup = asset_lookup_strategy or MessageAssetIdLookupStrategy()
    resolver = AssetResolver()
    return [
        ChainOfThoughtMediaHandler(),
        SceneMediaHandler(lookup, resolver),
        SystemDialogMediaHandler(),
        BgmMediaHandler(lookup, resolver),
        CgMediaHandler(),
        CharacterMediaHandler(
            asset_lookup_strategy=lookup,
            sprite_resolver=sprite_resolver,
            tts_generation_strategy=tts_generation_strategy,
            casting_map_provider=casting_map_provider,
        ),
    ]


__all__ = [
    "BgmMediaHandler",
    "CgMediaHandler",
    "ChainOfThoughtMediaHandler",
    "CharacterMediaHandler",
    "SceneMediaHandler",
    "SystemDialogMediaHandler",
    "get_dialog_media_handlers",
]
