"""
TTS worker 用 LLM dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :mod:`application.runtime.context` 取得，不引用 worker 类型。
"""

from __future__ import annotations

import traceback
from typing import List

from application.chat.tts import (
    ConfigSpriteLookupStrategy,
    DefaultTtsGenerationStrategy,
    SpriteLookupRequest,
    SpriteLookupStrategy,
    TtsGenerationRequest,
    TtsGenerationStrategy,
)
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_tts,
    match_system_dialog_tts,
    normalize_character_name,
)
from application.runtime.context import get_app_runtime, tts_emit_to_ui_queue
from i18n import tr as tr_i18n
from sdk.handlers import MessageHandler
from sdk.messages import LLMDialogMessage


def _post_tts_busy(text: str) -> None:
    try:
        get_app_runtime().ui_update_manager.post_busy_bar(text, 0.0)
    except Exception:
        pass


def _hide_tts_busy() -> None:
    try:
        get_app_runtime().ui_update_manager.hide_busy_bar()
    except Exception:
        pass


def _cc():
    return get_app_runtime().opencc


class ChainOfThoughtTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cot_tts(_cc(), msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        disp_name = _cc().convert(normalize_character_name(msg.name))
        tts_emit_to_ui_queue(
            disp_name,
            msg.text or "",
            str(msg.asset_id if msg.asset_id is not None else "-1"),
            "",
            is_system_message=True,
            effect=msg.effect or "",
        )


class SystemDialogTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_system_dialog_tts(_cc(), msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        disp_name = _cc().convert(normalize_character_name(msg.name))
        tts_emit_to_ui_queue(
            disp_name,
            msg.text,
            str(msg.asset_id),
            "",
            is_system_message=True,
            effect=msg.effect,
        )


class BgmTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_bgm_name(msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        bgm_path = ""
        try:
            sid = int(msg.asset_id) - 1
            bgm_path = rt.bgm_list[sid]
        except Exception as e:
            print("无法得到bgm path", e)
            traceback.print_exc()
        finally:
            tts_emit_to_ui_queue(
                "bgm",
                "",
                str(msg.asset_id),
                bgm_path,
                is_system_message=True,
                effect=msg.effect,
            )


class CgTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cg_name(msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        _post_tts_busy(tr_i18n("desktop.tts_busy_cg"))
        try:
            cg_path = get_app_runtime().t2i_manager.t2i(
                prompt=msg.text, prompt_processor=None
            )
            tts_emit_to_ui_queue(
                msg.name, msg.text, "-1", cg_path, is_system_message=True
            )
        except Exception as e:
            print(f"生成CG失败，{e}")
            traceback.print_exc()
        finally:
            _hide_tts_busy()


class DefaultCharacterTtsHandler(MessageHandler):
    """有角色立绘的常规 TTS 路径（末项，始终匹配）。"""

    def __init__(
        self,
        sprite_lookup_strategy: SpriteLookupStrategy | None = None,
        tts_generation_strategy: TtsGenerationStrategy | None = None,
    ) -> None:
        self.sprite_lookup_strategy = (
            ConfigSpriteLookupStrategy()
            if sprite_lookup_strategy is None
            else sprite_lookup_strategy
        )
        self.tts_generation_strategy = (
            DefaultTtsGenerationStrategy()
            if tts_generation_strategy is None
            else tts_generation_strategy
        )

    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return True

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        name_s = _cc().convert(msg.name)
        character_config = rt.config.get_character_by_name(name_s)
        if character_config is None:
            raise ValueError(f"未找到角色配置: {name_s}")

        sprite = self.sprite_lookup_strategy.lookup(
            SpriteLookupRequest(character=character_config, message=msg)
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
            _post_tts_busy(tr_i18n("desktop.tts_busy_synthesizing", name=name_s))
        try:
            for output in self.tts_generation_strategy.generate(generation_request):
                rt.audio_path_queue.put(output)
        finally:
            if show_busy:
                _hide_tts_busy()


def get_tts_handlers(
    *,
    sprite_lookup_strategy: SpriteLookupStrategy | None = None,
    tts_generation_strategy: TtsGenerationStrategy | None = None,
) -> List[MessageHandler]:
    return [
        ChainOfThoughtTtsHandler(),
        SystemDialogTtsHandler(),
        BgmTtsHandler(),
        CgTtsHandler(),
        DefaultCharacterTtsHandler(
            sprite_lookup_strategy=sprite_lookup_strategy,
            tts_generation_strategy=tts_generation_strategy,
        ),
    ]
