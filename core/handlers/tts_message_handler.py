"""
TTS worker 用 LLM dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :func:`core.runtime.app_runtime.get_app_runtime` 取得，不引用 worker 类型。
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import List

from config.config_manager import ConfigManager
from core.runtime.app_runtime import get_app_runtime, tts_emit_to_ui_queue, tts_item_done_only
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_tts,
    match_system_dialog_tts,
    normalize_character_name,
)
from core.handlers.handler_registry import MessageHandler
from core.messaging.message import LLMDialogMessage

_config = ConfigManager()


def get_character_by_name(name: str):
    return _config.get_character_by_name(name)


def _cc():
    return get_app_runtime().opencc


class ChainOfThoughtTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cot_tts(_cc(), msg.character_name)

    def handle(self, msg: LLMDialogMessage) -> None:
        tts_item_done_only()
        print("TTSWorker: COT", msg.speech)


class SystemDialogTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_system_dialog_tts(_cc(), msg.character_name)

    def handle(self, msg: LLMDialogMessage) -> None:
        name = _cc().convert(normalize_character_name(msg.character_name))
        tts_emit_to_ui_queue(
            name,
            msg.speech,
            str(msg.sprite),
            "",
            is_system_message=True,
            effect=msg.effect,
        )


class BgmTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_bgm_name(msg.character_name)

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        bgm_path = ""
        try:
            sid = int(msg.sprite) - 1
            bgm_path = rt.bgm_list[sid]
        except Exception as e:
            print("无法得到bgm path", e)
            traceback.print_exc()
        finally:
            tts_emit_to_ui_queue(
                "bgm", "", str(msg.sprite), bgm_path, is_system_message=True, effect=msg.effect
            )


class CgTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cg_name(msg.character_name)

    def handle(self, msg: LLMDialogMessage) -> None:
        try:
            cg_path = get_app_runtime().t2i_manager.t2i(prompt=msg.speech, prompt_processor=None)
            tts_emit_to_ui_queue(
                msg.character_name, msg.speech, "-1", cg_path, is_system_message=True
            )
        except Exception as e:
            print(f"生成CG失败，{e}")
            traceback.print_exc()


class DefaultCharacterTtsHandler(MessageHandler):
    """有角色立绘的常规 TTS 路径（末项，始终匹配）。"""

    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return True

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        name_s = _cc().convert(msg.character_name)
        character_config = get_character_by_name(name_s)
        if character_config is None:
            raise ValueError(f"未找到角色配置: {name_s}")
        translate = msg.translate
        speech = msg.speech
        sprite = msg.sprite
        text_processor = rt.text_processor
        speech_text = speech
        if translate:
            text_processor = None
            speech_text = rt.text_processor.remove_parentheses(translate)
        audio_path = ""
        if rt.tts_manager:
            model_info = {
                "character_name": name_s,
                "sovits_model_path": Path(character_config.sovits_model_path).resolve().as_posix(),
                "gpt_model_path": Path(character_config.gpt_model_path).resolve().as_posix(),
            }
            rt.tts_manager.switch_model(model_info)
            print("TTSWorker: 使用模型", name_s, model_info)
            try:
                sprite_id = int(sprite) - 1
                if sprite_id < 0 or sprite_id >= len(character_config.sprites):
                    raise IndexError("Sprite ID out of range")
            except (ValueError, IndexError):
                print(f"无效或缺失的立绘编号: {sprite}. 使用默认立绘。")
                sprite_id = -1
            ref_audio_path = Path(character_config.refer_audio_path).resolve().as_posix()
            prompt_text = character_config.prompt_text
            try:
                sprite_data = character_config.sprites[sprite_id]
                if sprite_data.get("voice_text", None):
                    ref_audio_path = Path(sprite_data.get("voice_path")).resolve().as_posix()
                    prompt_text = sprite_data.get("voice_text")
            except Exception:
                print("没有立绘")
            if text_processor:
                speech_text = text_processor.remove_parentheses(speech_text)
            audio_path = rt.tts_manager.generate_tts(
                speech_text,
                text_processor=text_processor,
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                prompt_lang=character_config.prompt_lang,
                character_name=name_s,
            )
        else:
            audio_path = character_config.sprites[int(sprite) - 1].get("voice_path", "")
        tts_emit_to_ui_queue(
            name_s, speech, str(sprite), audio_path, is_system_message=False, effect=msg.effect
        )


def get_tts_handlers() -> List[MessageHandler]:
    return [
        ChainOfThoughtTtsHandler(),
        SystemDialogTtsHandler(),
        BgmTtsHandler(),
        CgTtsHandler(),
        DefaultCharacterTtsHandler(),
    ]
