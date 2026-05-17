"""
TTS worker 用 LLM dialog 处理器（见 handler_registry.MessageHandler）。

依赖从 :func:`core.runtime.app_runtime.get_app_runtime` 取得，不引用 worker 类型。
"""

from __future__ import annotations

import re
import traceback
import wave
from pathlib import Path
from typing import List

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
from core.runtime.app_runtime import (
    get_app_runtime,
    tts_emit_to_ui_queue,
    tts_item_done_only,
)
from i18n import tr as tr_i18n

_config = ConfigManager()
_GPT_SOVITS_REF_MIN_SECONDS = 3.0
_GPT_SOVITS_REF_MAX_SECONDS = 10.0
_GPT_SOVITS_REF_TARGET_SECONDS = 3.4
_USE_SPRITE_REF_AUDIO_FOR_GPT_SOVITS = False


def get_character_by_name(name: str):
    return _config.get_character_by_name(name)


def _sprite_value(sprite_data, key: str, default=None):
    if isinstance(sprite_data, dict):
        return sprite_data.get(key, default)
    return getattr(sprite_data, key, default)


def _wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()
    except Exception:
        return None


def _has_speakable_text(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]", str(text or "")))


def _prepare_gpt_sovits_ref_audio(path: Path) -> Path | None:
    duration = _wav_duration_seconds(path)
    if duration is None:
        return path
    if _GPT_SOVITS_REF_MIN_SECONDS <= duration <= _GPT_SOVITS_REF_MAX_SECONDS:
        return path
    if duration <= 0 or duration > _GPT_SOVITS_REF_MIN_SECONDS:
        return None

    cache_dir = Path("cache/tts_refs")
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / f"{path.stem}_gpt_sovits_ref.wav"
    cached_duration = _wav_duration_seconds(output_path)
    if cached_duration and _GPT_SOVITS_REF_MIN_SECONDS <= cached_duration <= _GPT_SOVITS_REF_MAX_SECONDS:
        return output_path.resolve()

    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            frame_rate = source.getframerate()
            frames_per_clip = source.getnframes()
            clip_frames = source.readframes(frames_per_clip)

        silence_frames = max(1, int(frame_rate * 0.08))
        silence = b"\x00" * silence_frames * channels * sample_width
        target_frames = int(frame_rate * _GPT_SOVITS_REF_TARGET_SECONDS)
        max_frames = int(frame_rate * _GPT_SOVITS_REF_MAX_SECONDS)

        chunks: list[bytes] = []
        total_frames = 0
        while total_frames < target_frames and total_frames + frames_per_clip <= max_frames:
            chunks.append(clip_frames)
            total_frames += frames_per_clip
            if total_frames < target_frames and total_frames + silence_frames <= max_frames:
                chunks.append(silence)
                total_frames += silence_frames

        if total_frames < int(frame_rate * _GPT_SOVITS_REF_MIN_SECONDS):
            return None

        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(frame_rate)
            output.writeframes(b"".join(chunks))
        return output_path.resolve()
    except Exception as exc:
        print(f"立绘参考音频缓存生成失败: {path} ({exc})")
        return None


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


def _ensure_t2i_manager():
    rt = get_app_runtime()
    if rt.t2i_manager is not None:
        return rt.t2i_manager

    from t2i.t2i_manager import T2IAdapterFactory, T2IManager

    api = rt.config.config.api_config
    adapter_name = str(api.t2i_provider or "comfyui")
    base_kwargs = {
        "work_path": api.t2i_work_path,
        "api_url": api.t2i_api_url,
        "workflow_path": api.t2i_default_workflow_path,
        "prompt_node_id": api.t2i_prompt_node_id,
        "output_node_id": api.t2i_output_node_id,
    }
    adapter = T2IAdapterFactory.create_adapter(
        adapter_name=adapter_name,
        **rt.config.merged_t2i_factory_kwargs(adapter_name, base_kwargs),
    )
    rt.t2i_manager = T2IManager(adapter)
    return rt.t2i_manager


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
        emitted = False
        try:
            manager = _ensure_t2i_manager()
            prompt = (msg.text or "").strip()
            if not prompt:
                raise ValueError("CG prompt is empty.")
            cg_path = manager.t2i(
                prompt=prompt,
                prompt_processor=None,
                image_size="landscape",
            )
            if not cg_path:
                raise RuntimeError("T2I returned no image path.")
            tts_emit_to_ui_queue(
                msg.name, prompt, "-1", cg_path, is_system_message=True
            )
            emitted = True
        except Exception as e:
            print(f"生成CG失败，{e}")
            traceback.print_exc()
            try:
                tts_emit_to_ui_queue(
                    "system",
                    tr_i18n("desktop.cg_generate_failed", error=str(e)),
                    "-1",
                    "",
                    is_system_message=True,
                )
                emitted = True
            except Exception:
                if not emitted:
                    tts_item_done_only()
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
        voice_lang = str(_config.config.system_config.voice_language or "ja").strip().lower()
        translate = msg.translate if voice_lang.startswith("ja") else ""
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
                ref_audio_path = Path(character_config.refer_audio_path).resolve().as_posix()
                prompt_text = character_config.prompt_text
                aux_ref_audio_paths: list[str] = []
                try:
                    if _USE_SPRITE_REF_AUDIO_FOR_GPT_SOVITS and sprite_id >= 0:
                        sprite_data = character_config.sprites[sprite_id]
                        sprite_voice_path = _sprite_value(sprite_data, "voice_path")
                        sprite_voice_text = _sprite_value(sprite_data, "voice_text", "")
                        if sprite_voice_path:
                            sprite_ref_audio = Path(sprite_voice_path).resolve()
                            if sprite_ref_audio.exists():
                                prepared_ref_audio = _prepare_gpt_sovits_ref_audio(sprite_ref_audio)
                                if prepared_ref_audio:
                                    sprite_prompt_text = (sprite_voice_text or "").strip()
                                    if sprite_prompt_text:
                                        ref_audio_path = prepared_ref_audio.as_posix()
                                        prompt_text = sprite_prompt_text
                                    else:
                                        aux_ref_audio_paths.append(prepared_ref_audio.as_posix())
                                else:
                                    print(
                                        "立绘参考音频时长不适合 GPT-SoVITS 主参考，"
                                        f"已使用默认参考: {sprite_voice_path}"
                                    )
                            else:
                                print(f"立绘参考音频不存在: {sprite_voice_path}")
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
                if not _has_speakable_text(speech_text):
                    print("TTSWorker: 跳过无可读文本的语音片段。")
                    audio_path = ""
                elif not _sentences or len(_sentences) <= 1:
                    audio_path = rt.tts_manager.generate_tts(
                        speech_text,
                        text_processor=text_processor,
                        ref_audio_path=ref_audio_path,
                        aux_ref_audio_paths=aux_ref_audio_paths,
                        prompt_text=prompt_text,
                        prompt_lang=character_config.prompt_lang,
                        character_name=name_s,
                        speed_factor=_speed,
                    )
                else:
                    _asset_str = str(asset_id)
                    for _i, _sent in enumerate(_sentences):
                        if _has_speakable_text(_sent):
                            _path = rt.tts_manager.generate_tts(
                                _sent,
                                text_processor=text_processor,
                                ref_audio_path=ref_audio_path,
                                aux_ref_audio_paths=aux_ref_audio_paths,
                                prompt_text=prompt_text,
                                prompt_lang=character_config.prompt_lang,
                                character_name=name_s,
                                speed_factor=_speed,
                            )
                        else:
                            _path = ""
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
                    rt.tts_queue.task_done()
                    return  # already emitted per-sentence, skip final tts_emit_to_ui_queue
            finally:
                _hide_tts_busy()
        else:
            sprite_data = character_config.sprites[int(asset_id) - 1]
            audio_path = _sprite_value(sprite_data, "voice_path", "")
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
