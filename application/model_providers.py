"""Application-facing model-provider discovery helpers."""

from __future__ import annotations

from typing import Any

from ai.llm.claude_url import (
    claude_messages_endpoint_url,
    claude_models_endpoint_url,
)
from application.runtime.state import _jsonify
from config.models.llm_defaults import LLM_BASE_URLS

_TTS_LABEL_PREFS: tuple[tuple[str, str], ...] = (
    ("genie-tts", "Genie TTS"),
    ("kaggle-gpt-sovits", "Kaggle GPT-SoVITS"),
    ("gpt-sovits", "GPT SoVITS"),
    ("index-tts", "IndexTTS"),
    ("cosyvoice", "CosyVoice"),
)
_PREFERRED_T2I_KEYS_LOWER: tuple[str, ...] = ("comfyui", "stable diffusion")


def _adapter_schema(adapter_class: Any | None) -> dict[str, Any]:
    if adapter_class is None:
        return {}
    getter = getattr(adapter_class, "get_config_schema", None)
    if not callable(getter):
        return {}
    try:
        schema = getter()
    except Exception:
        return {}
    return _jsonify(schema) if isinstance(schema, dict) else {}


def _adapter_option(
    value: str,
    label: str,
    adapter_class: Any | None = None,
) -> dict[str, Any]:
    return {
        "label": str(label or value),
        "schema": _adapter_schema(adapter_class),
        "value": str(value),
    }


def adapter_catalog() -> dict[str, list[dict[str, Any]]]:
    """Return registered model adapters without exposing AI imports to transport."""

    try:
        from ai.asr.asr_manager import ASRAdapterFactory
        from ai.llm.llm_manager import LLMAdapterFactory
        from ai.t2i.t2i_manager import T2IAdapterFactory
        from ai.tts.tts_manager import TTSAdapterFactory
    except Exception:
        return {"asr": [], "llm": [], "t2i": [], "tts": []}

    llm_adapters = dict(LLMAdapterFactory._adapters)
    llm: list[dict[str, Any]] = []
    for key in LLM_BASE_URLS:
        if key in llm_adapters:
            llm.append(_adapter_option(key, key, llm_adapters[key]))
    for key in sorted(llm_adapters, key=str.lower):
        if key not in {item["value"] for item in llm}:
            llm.append(_adapter_option(key, key, llm_adapters[key]))

    tts_adapters = dict(TTSAdapterFactory._adapters)
    tts: list[dict[str, Any]] = [_adapter_option("none", "不使用")]
    by_lower = {key.lower(): key for key in tts_adapters}
    seen: set[str] = set()
    for slug, label in _TTS_LABEL_PREFS:
        canonical = by_lower.get(slug)
        if canonical:
            tts.append(_adapter_option(canonical, label, tts_adapters[canonical]))
            seen.add(canonical)
    for key in sorted(tts_adapters, key=str.lower):
        if key not in seen:
            tts.append(
                _adapter_option(
                    key,
                    key.replace("-", " ").title(),
                    tts_adapters[key],
                )
            )

    t2i_adapters = dict(T2IAdapterFactory._adapters)
    t2i_by_lower = {key.lower(): key for key in t2i_adapters}
    fixed_t2i_labels = {
        "comfyui": "ComfyUI",
        "stable diffusion": "Stable Diffusion",
    }
    t2i: list[dict[str, Any]] = []
    for preferred in _PREFERRED_T2I_KEYS_LOWER:
        canonical = t2i_by_lower.get(preferred)
        if canonical:
            t2i.append(
                _adapter_option(
                    canonical,
                    fixed_t2i_labels.get(
                        canonical.lower(),
                        canonical.replace("-", " ").title(),
                    ),
                    t2i_adapters[canonical],
                )
            )
    for key in sorted(t2i_adapters, key=str.lower):
        if key not in {item["value"] for item in t2i}:
            t2i.append(
                _adapter_option(
                    key,
                    fixed_t2i_labels.get(
                        key.lower(),
                        key.replace("-", " ").title(),
                    ),
                    t2i_adapters[key],
                )
            )

    asr_adapters = dict(ASRAdapterFactory._adapters)
    asr_labels = {
        "faster_whisper": "faster-whisper",
        "realtime_stt": "RealtimeSTT",
        "vosk": "Vosk",
    }
    asr: list[dict[str, Any]] = []
    if "vosk" in asr_adapters:
        asr.append(_adapter_option("vosk", asr_labels["vosk"], asr_adapters["vosk"]))
    for key in sorted(key for key in asr_adapters if key != "vosk"):
        asr.append(_adapter_option(key, asr_labels.get(key, key), asr_adapters[key]))

    return {"asr": asr, "llm": llm, "t2i": t2i, "tts": tts}


def normalize_t2i_provider(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "comfyui"
    try:
        from ai.t2i.t2i_manager import T2IAdapterFactory

        lowered = raw.lower()
        for key in T2IAdapterFactory._adapters:
            if key.lower() == lowered:
                return key
    except Exception:
        pass
    return raw


__all__ = [
    "adapter_catalog",
    "claude_messages_endpoint_url",
    "claude_models_endpoint_url",
    "normalize_t2i_provider",
]
