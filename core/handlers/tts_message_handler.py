"""
TTS worker 用 LLM dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :func:`core.runtime.app_runtime.get_app_runtime` 取得，不引用 worker 类型。
"""

from __future__ import annotations

import logging
import re
import traceback
from pathlib import Path
from typing import List
from urllib.parse import urlparse

import yaml
from config.config_manager import ConfigManager
from sdk.handlers import MessageHandler
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_tts,
    match_system_dialog_tts,
    normalize_character_name,
)
from sdk.messages import LLMDialogMessage, TTSOutputMessage
from core.runtime.app_runtime import get_app_runtime, tts_emit_to_ui_queue
from i18n import tr as tr_i18n

_config = ConfigManager()
logger = logging.getLogger(__name__)


def _read_sprite_voice_cfg(name_s: str, sprite_id: int):
    """直接从 YAML 读取立绘的 voice_type、voice_path、voice_text，避免跨进程缓存。"""
    try:
        _chars_path = Path("data/config/characters.yaml")
        if not _chars_path.is_file():
            return None, None, None
        with open(_chars_path, "r", encoding="utf-8") as _fh:
            _data = yaml.safe_load(_fh) or []
        for _c in _data:
            if _c.get("name") == name_s:
                _sprites = _c.get("sprites") or []
                if 0 <= sprite_id < len(_sprites):
                    _s = _sprites[sprite_id]
                    return _s.get("voice_type"), _s.get("voice_path"), _s.get("voice_text")
    except Exception:
        pass
    return None, None, None


def get_character_by_name(name: str):
    return _config.get_character_by_name(name)


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


def _is_remote_gpt_sovits() -> bool:
    try:
        api_config = _config.config.api_config
        provider = str(getattr(api_config, "tts_provider", "") or "").strip().lower()
        host = (urlparse(str(getattr(api_config, "gpt_sovits_url", "") or "")).hostname or "").lower()
        return provider == "kaggle-gpt-sovits" or (
            provider == "gpt-sovits" and host not in {"", "127.0.0.1", "localhost", "0.0.0.0", "::1"}
        )
    except Exception:
        return False


def _is_remote_reference_path(path: str) -> bool:
    return str(path or "").strip().startswith("/kaggle/")


def _sprite_value(sprite_data, key: str, default=None):
    if isinstance(sprite_data, dict):
        return sprite_data.get(key, default)
    return getattr(sprite_data, key, default)


def _resolve_sprite_voice_cfg(character_config, sprite_id: int):
    """Return (voice_type, voice_path, voice_text) for a sprite, YAML-first.

    Voice uploads are handled in a separate bridge process, so the in-process
    ``character_config`` cache can still point at a replaced or deleted file.
    Read characters.yaml first and fall back to the cached snapshot only when the
    YAML has no path for this sprite.
    """
    yaml_voice_type, yaml_voice_path, yaml_voice_text = _read_sprite_voice_cfg(
        character_config.name, sprite_id
    )
    voice_type = yaml_voice_type
    voice_path = str(yaml_voice_path or "").strip()
    voice_text = yaml_voice_text or ""
    if not voice_path:
        sprite_data = character_config.sprites[sprite_id]
        voice_type = _sprite_value(sprite_data, "voice_type")
        voice_path = str(_sprite_value(sprite_data, "voice_path", "") or "").strip()
        voice_text = _sprite_value(sprite_data, "voice_text", "") or ""
    return voice_type, voice_path, voice_text


def _sprite_voice_audio(character_config, sprite_id: int, *allowed_types: str):
    if sprite_id < 0:
        return None, "", ""
    try:
        voice_type, voice_path, voice_text = _resolve_sprite_voice_cfg(
            character_config, sprite_id
        )
        # Require the audio file to actually exist: both callers play this path
        # directly, so a stale config entry whose file was deleted must fall
        # through (return None) to synthesis / the default reference instead of
        # playing a missing file.
        if voice_type in allowed_types and voice_path and Path(voice_path).is_file():
            return voice_type, Path(voice_path).resolve().as_posix(), voice_text
    except Exception:
        logger.debug(
            "Failed to resolve sprite voice audio for character=%s sprite_id=%s",
            getattr(character_config, "name", None),
            sprite_id,
            exc_info=True,
        )
    return None, "", ""


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
                "bgm", "", str(msg.asset_id), bgm_path, is_system_message=True, effect=msg.effect
            )


class CgTtsHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return match_cg_name(msg.name)

    def handle(self, msg: LLMDialogMessage) -> None:
        _post_tts_busy(tr_i18n("desktop.tts_busy_cg"))
        try:
            cg_path = get_app_runtime().t2i_manager.t2i(prompt=msg.text, prompt_processor=None)
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

    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return True

    def handle(self, msg: LLMDialogMessage) -> None:
        rt = get_app_runtime()
        name_s = _cc().convert(msg.name)
        character_config = get_character_by_name(name_s)
        if character_config is None:
            raise ValueError(f"未找到角色配置: {name_s}")
        translate = msg.translate
        speech = msg.text
        asset_id = msg.asset_id
        text_processor = rt.text_processor
        speech_text = speech
        if translate:
            text_processor = None
            speech_text = rt.text_processor.remove_parentheses(translate)
            speech_text = rt.text_processor.replace_names(speech_text)
        audio_path = ""
        if rt.tts_manager:
            _post_tts_busy(tr_i18n("desktop.tts_busy_synthesizing", name=name_s))
            try:
                model_info = {
                    "character_name": name_s,
                    "sovits_model_path": Path(character_config.sovits_model_path).resolve().as_posix(),
                    "gpt_model_path": Path(character_config.gpt_model_path).resolve().as_posix(),
                }
                rt.tts_manager.switch_model(model_info)
                print("TTSWorker: 使用模型", name_s, model_info)
                try:
                    sprite_id = int(asset_id) - 1
                    if sprite_id < 0 or sprite_id >= len(character_config.sprites):
                        raise IndexError("Sprite ID out of range")
                except (ValueError, IndexError):
                    print(f"无效或缺失的立绘编号: {asset_id}. 使用默认立绘。")
                    sprite_id = -1

                # 预设语音：跳过 TTS 合成，直接播放立绘上传的语音文件
                if sprite_id >= 0:
                    _voice_type, _voice_audio_path, _voice_text = _sprite_voice_audio(
                        character_config, sprite_id, "preset"
                    )
                    if _voice_audio_path:
                        _hide_tts_busy()
                        tts_emit_to_ui_queue(
                            name_s, _voice_text or speech, str(asset_id), _voice_audio_path,
                            is_system_message=False, effect=msg.effect,
                        )
                        return

                ref_audio_path = Path(character_config.refer_audio_path).resolve().as_posix()
                prompt_text = character_config.prompt_text
                try:
                    if sprite_id < 0:
                        raise IndexError("Sprite ID out of range")
                    # YAML-first (see _resolve_sprite_voice_cfg): a reference voice
                    # replaced via the bridge writes a new content-hash path and
                    # deletes the old one, but this process's character_config cache
                    # still holds the old path.  Reading the snapshot here would keep
                    # falling back to the default reference until the chat restarts.
                    _voice_type, _vp, _vt = _resolve_sprite_voice_cfg(
                        character_config, sprite_id
                    )
                    # Only use the sprite's reference voice when it is actually
                    # available; a stale config path whose file was deleted/moved
                    # must fall back to the character default rather than being
                    # sent to GPT-SoVITS (which fails with HTTP 400 "not exists").
                    _vp_available = (
                        _is_remote_reference_path(_vp) if _is_remote_gpt_sovits() else Path(_vp).is_file()
                    )
                    if _vp and _vp_available and (_voice_type == "reference" or (_voice_type is None and _vt)) and _vt:
                        ref_audio_path = Path(_vp).resolve().as_posix()
                        prompt_text = _vt
                    elif _vp and not _vp_available:
                        print(f"参考语音文件不存在，回退默认参考合成: {_vp}")
                except Exception:
                    print("没有立绘")
                if text_processor:
                    speech_text = text_processor.remove_parentheses(speech_text)

                # 根据配置决定是否分句发送
                _api_cfg = _config.config.api_config
                _split_enabled = getattr(_api_cfg, "tts_split_enabled", False)
                _max_len = getattr(_api_cfg, "tts_max_sentence_length", 15)

                _sentences: list[str] = []
                if _split_enabled:
                    _pieces = re.split(r'(?<=[。！？，、；：\.!\?,;:])', speech_text)
                    _pieces = [s.strip() for s in _pieces if s.strip()]
                    _cur = ""
                    for _p in _pieces:
                        if not _cur:
                            _cur = _p
                        elif len(_cur) + len(_p) <= _max_len:
                            _cur += _p
                        else:
                            _sentences.append(_cur)
                            _cur = _p
                    if _cur:
                        _sentences.append(_cur)

                _speed = character_config.speech_speed
                if not _sentences or len(_sentences) <= 1:
                    audio_path = rt.tts_manager.generate_tts(
                        speech_text,
                        text_processor=text_processor,
                        ref_audio_path=ref_audio_path,
                        prompt_text=prompt_text,
                        prompt_lang=character_config.prompt_lang,
                        character_name=name_s,
                        speed_factor=_speed,
                    )
                else:
                    _asset_str = str(asset_id)
                    for _i, _sent in enumerate(_sentences):
                        _path = rt.tts_manager.generate_tts(
                            _sent,
                            text_processor=text_processor,
                            ref_audio_path=ref_audio_path,
                            prompt_text=prompt_text,
                            prompt_lang=character_config.prompt_lang,
                            character_name=name_s,
                            speed_factor=_speed,
                        )
                        if not _path or not Path(_path).is_file() or Path(_path).stat().st_size <= 0:
                            print(
                                "TTSWorker: 分句语音生成失败，停止后续分句播放，"
                                f"segment={_i + 1}/{len(_sentences)}, text={_sent!r}"
                            )
                            tts_emit_to_ui_queue(
                                name_s,
                                speech,
                                _asset_str,
                                "",
                                is_system_message=False,
                                effect=msg.effect,
                            )
                            return
                        _is_first = _i == 0
                        _is_last = _i == len(_sentences) - 1
                        rt.audio_path_queue.put(TTSOutputMessage(
                            audio_path=_path or "",
                            name=name_s,
                            text=speech if _is_first else "",
                            asset_id=_asset_str if _is_first else _asset_str,
                            effect=msg.effect if _is_first else "",
                            is_final_segment=_is_last,
                            timeout=None if _is_first else 0,
                        ))
                    return  # already emitted per-sentence, skip final tts_emit_to_ui_queue
            finally:
                _hide_tts_busy()
        else:
            try:
                sprite_id = int(asset_id) - 1
            except (TypeError, ValueError):
                sprite_id = -1
            _voice_type, audio_path, _voice_text = _sprite_voice_audio(
                character_config, sprite_id, "fallback", "preset"
            )
        tts_emit_to_ui_queue(
            name_s, speech, str(asset_id), audio_path, is_system_message=False, effect=msg.effect,
        )


def get_tts_handlers() -> List[MessageHandler]:
    return [
        ChainOfThoughtTtsHandler(),
        SystemDialogTtsHandler(),
        BgmTtsHandler(),
        CgTtsHandler(),
        DefaultCharacterTtsHandler(),
    ]
