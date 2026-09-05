"""
dialog media worker 用 LLM dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :mod:`application.runtime.context` 取得，不引用 worker 类型。
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable, Iterator
from typing import List

from application.chat.dialog_media import (
    AssetResolver,
    AssetLookupRequest,
    AssetLookupStrategy,
    asset_candidates,
    DefaultTtsGenerationStrategy,
    MessageAssetIdLookupStrategy,
    ResolvedSpriteAsset,
    SpriteAssetResolver,
    TtsGenerationRequest,
    TtsGenerationStrategy,
)
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_dialog,
    match_system_dialog,
    match_scene_name,
    normalize_character_name,
)
from application.runtime.context import get_app_runtime, emit_presentation_message
from i18n import tr as tr_i18n
from sdk.handlers import MessageHandler
from sdk.messages import LLMDialogMessage, PresentationMessage
from core.media.asset_tags import tag_contents


def _post_media_busy(text: str) -> None:
    try:
        get_app_runtime().ui_update_manager.post_busy_bar(text, 0.0)
    except Exception:
        pass


def _hide_media_busy() -> None:
    try:
        get_app_runtime().ui_update_manager.hide_busy_bar()
    except Exception:
        pass


def _cc():
    return get_app_runtime().opencc


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


def _lookup_request(
    msg: LLMDialogMessage,
    *,
    scope: str,
    candidates,
) -> AssetLookupRequest:
    return AssetLookupRequest(
        scope=scope,
        candidates=tuple(candidates),
        explicit_asset_id=str(msg.asset_id if msg.asset_id is not None else "-1"),
        vibe=str(msg.vibe or ""),
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
        return match_scene_name(msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        background = rt.background
        sprites = list(getattr(background, "sprites", None) or [])
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
        emit_presentation_message(
            normalize_character_name(msg.name),
            msg.text,
            resolved.asset_id,
            "",
            is_system_message=True,
            effect=msg.effect,
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
        background = rt.background
        paths = list(rt.bgm_list or [])
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


class CharacterMediaHandler(MessageHandler):
    """处理带角色立绘的常规对话（末项，始终匹配）。"""

    def __init__(
        self,
        asset_lookup_strategy: AssetLookupStrategy | None = None,
        tts_generation_strategy: TtsGenerationStrategy | None = None,
        sprite_resolver: SpriteAssetResolver | None = None,
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
                name=character_name,
                text=speech if first else "",
                asset_id=sprite.asset_id,
                effect=(message.effect or "") if first else "",
                is_system_message=False,
                is_final_segment=is_final,
                timeout=None if first else 0,
            )

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        name_s = _cc().convert(msg.name)
        character_config = rt.config.get_character_by_name(name_s)
        if character_config is None:
            raise ValueError(f"未找到角色配置: {name_s}")

        candidates = self.sprite_resolver.candidates(character_config)
        lookup_result = self.asset_lookup_strategy.lookup(
            _lookup_request(
                msg,
                scope=f"sprite:{name_s}",
                candidates=candidates,
            )
        )
        sprite = self.sprite_resolver.resolve(
            character_config,
            candidates,
            lookup_result,
        )
        generation_request = TtsGenerationRequest(
            runtime=rt,
            character=character_config,
            character_name=name_s,
            message=msg,
            sprite=sprite,
        )
        show_busy = rt.tts_manager is not None
        if show_busy:
            _post_media_busy(tr_i18n("desktop.tts_busy_synthesizing", name=name_s))
        try:
            audio_paths = self.tts_generation_strategy.generate(generation_request)
            for output in self._presentation_messages(
                character_name=name_s,
                message=msg,
                sprite=sprite,
                audio_paths=audio_paths,
            ):
                rt.presentation_queue.put(output)
        finally:
            if show_busy:
                _hide_media_busy()


def get_dialog_media_handlers(
    *,
    asset_lookup_strategy: AssetLookupStrategy | None = None,
    sprite_resolver: SpriteAssetResolver | None = None,
    tts_generation_strategy: TtsGenerationStrategy | None = None,
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
        ),
    ]
