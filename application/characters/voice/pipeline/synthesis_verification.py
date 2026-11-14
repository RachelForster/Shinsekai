"""Short-phrase TTS synthesis verification under exclusive model session lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.tts.model_session import tts_model_session
from ai.tts.tts_manager import TTSAdapterFactory
from application.characters.voice.pipeline.wav_acoustics import analyze_wav_acoustics


_VERIFY_PHRASES = {
    "ja": "こんにちは、よろしくね。",
    "zh": "你好，请多指教。",
    "en": "Hello, nice to meet you.",
}


def verify_tts_synthesis(
    state: Any,
    *,
    gsv_url: str,
    gsv_root: Path,
    character_name: str,
    gpt_model_path: str,
    sovits_model_path: str,
    refer_audio_path: str,
    prompt_text: str,
    prompt_lang: str,
    work_dir: Path,
) -> dict[str, Any]:
    """Switch to pretrained base or character weights and verify a short greeting synthesizes cleanly."""
    config_manager = state.config_manager
    merged_fn = getattr(config_manager, "merged_tts_factory_kwargs", None)
    base_kwargs = {
        "gpt_sovits_work_path": str(gsv_root),
        "tts_server_url": gsv_url,
    }
    kwargs = merged_fn("gpt-sovits", base_kwargs) if callable(merged_fn) else base_kwargs
    adapter = TTSAdapterFactory.create_adapter(
        "gpt-sovits",
        wait_until_ready=True,
        **kwargs,
    )
    verify_wav = work_dir / "verify_synthesis.wav"
    phrase = _VERIFY_PHRASES.get(prompt_lang, _VERIFY_PHRASES["ja"])
    try:
        with tts_model_session(adapter, gsv_url):
            adapter.switch_model(
                {
                    "character_name": character_name,
                    "gpt_model_path": gpt_model_path,
                    "sovits_model_path": sovits_model_path,
                }
            )
            generated = adapter.generate_speech(
                phrase,
                file_path=str(verify_wav),
                ref_audio_path=refer_audio_path,
                prompt_text=prompt_text,
                prompt_lang=prompt_lang,
                text_lang=prompt_lang if prompt_lang in {"ja", "zh", "en"} else "ja",
            )
        if not generated or not verify_wav.is_file() or verify_wav.stat().st_size <= 44:
            raise RuntimeError("TTS 短句合成自检失败：服务未返回有效音频数据。")
        acoustics = analyze_wav_acoustics(verify_wav)
        duration = round(acoustics.duration_seconds, 2) if acoustics is not None else None
        if acoustics is not None and acoustics.duration_seconds < 0.15:
            raise RuntimeError("TTS 短句合成自检失败：合成音频时长过短。")
        return {
            "verified": True,
            "testPhrase": phrase,
            "durationSeconds": duration,
            "activeGptWeights": getattr(adapter, "gpt_model_path", "") or "",
            "activeSovitsWeights": getattr(adapter, "sovits_model_path", "") or "",
        }
    finally:
        verify_wav.unlink(missing_ok=True)
        stop_fn = getattr(adapter, "stop_server", None)
        if callable(stop_fn):
            stop_fn()
