"""Application-facing model-provider discovery helpers."""

from __future__ import annotations

from typing import Any

from ai.llm.claude_url import (
    claude_messages_endpoint_url,
    claude_models_endpoint_url,
)
from application.runtime.state import _jsonify
from config.llm_defaults import LLM_BASE_URLS

_TTS_LABEL_PREFS: tuple[tuple[str, str], ...] = (
    ("genie-tts", "Genie TTS"),
    ("kaggle-gpt-sovits", "Kaggle GPT-SoVITS"),
    ("gpt-sovits", "GPT SoVITS"),
    ("qwen3-tts-gguf", "Qwen3-TTS (llama.cpp GGUF)"),
    ("index-tts", "IndexTTS"),
    ("cosyvoice", "CosyVoice"),
)
_PREFERRED_T2I_KEYS_LOWER: tuple[str, ...] = ("comfyui", "stable diffusion")
_FIXED_T2I_LABELS: dict[str, str] = {
    "comfyui": "ComfyUI",
    "stable diffusion": "Stable Diffusion",
}
_ASR_FALLBACK_LABELS: dict[str, str] = {
    "faster_whisper": "faster-whisper",
    "realtime_stt": "RealtimeSTT",
    "sherpa_onnx": "Sherpa-ONNX",
    "vosk": "Vosk",
}
_VISION_FALLBACK_LABELS: dict[str, str] = {
    "chatgpt": "OpenAI Vision",
    "claude": "Claude Vision",
    "deepseek": "DeepSeek Vision",
    "doubao": "豆包视觉",
    "gemini": "Gemini Vision",
    "moondream": "Moondream（本地）",
    "ollama": "Ollama Vision（本地）",
    "qwen": "通义千问视觉",
}


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


def _resolve_registration_class(registration: Any) -> Any | None:
    try:
        return registration.resolve_class()
    except Exception:
        return getattr(registration, "adapter_cls", None)


def adapter_catalog() -> dict[str, list[dict[str, Any]]]:
    """Return registered model adapters without exposing AI imports to transport."""
    try:
        from ai.asr.registry import get_asr_adapter_registry
        from ai.llm.registry import get_llm_adapter_registry
        from ai.t2i.registry import get_t2i_adapter_registry
        from ai.tts.registry import get_tts_adapter_registry
        from ai.vision.registry import get_vision_adapter_registry
    except Exception:
        return {"asr": [], "llm": [], "t2i": [], "tts": [], "vision": []}

    llm_entries = get_llm_adapter_registry().entries()
    llm_by_key = {entry.key: entry for entry in llm_entries}
    llm: list[dict[str, Any]] = []
    seen_llm: set[str] = set()
    for key in LLM_BASE_URLS:
        entry = llm_by_key.get(key)
        if entry is not None:
            llm.append(
                _adapter_option(
                    entry.key,
                    entry.label or entry.key,
                    _resolve_registration_class(entry),
                )
            )
            seen_llm.add(entry.key)
    for entry in sorted(llm_entries, key=lambda item: item.key.lower()):
        if entry.key not in seen_llm:
            llm.append(
                _adapter_option(
                    entry.key,
                    entry.label or entry.key,
                    _resolve_registration_class(entry),
                )
            )

    tts_entries = get_tts_adapter_registry().entries()
    tts: list[dict[str, Any]] = [_adapter_option("none", "不使用")]
    tts_by_lower = {entry.key.lower(): entry for entry in tts_entries}
    seen_tts: set[str] = set()
    for slug, pref_label in _TTS_LABEL_PREFS:
        entry = tts_by_lower.get(slug)
        if entry is not None:
            tts.append(
                _adapter_option(
                    entry.key,
                    entry.label or pref_label,
                    _resolve_registration_class(entry),
                )
            )
            seen_tts.add(entry.key)
    for entry in sorted(tts_entries, key=lambda item: item.key.lower()):
        if entry.key not in seen_tts:
            tts.append(
                _adapter_option(
                    entry.key,
                    entry.label or entry.key.replace("-", " ").title(),
                    _resolve_registration_class(entry),
                )
            )

    t2i_entries = get_t2i_adapter_registry().entries()
    t2i_by_lower = {entry.key.lower(): entry for entry in t2i_entries}
    t2i: list[dict[str, Any]] = []
    seen_t2i: set[str] = set()
    for preferred in _PREFERRED_T2I_KEYS_LOWER:
        entry = t2i_by_lower.get(preferred)
        if entry is not None:
            t2i.append(
                _adapter_option(
                    entry.key,
                    entry.label
                    or _FIXED_T2I_LABELS.get(
                        entry.key.lower(), entry.key.replace("-", " ").title()
                    ),
                    _resolve_registration_class(entry),
                )
            )
            seen_t2i.add(entry.key)
    for entry in sorted(t2i_entries, key=lambda item: item.key.lower()):
        if entry.key not in seen_t2i:
            t2i.append(
                _adapter_option(
                    entry.key,
                    entry.label
                    or _FIXED_T2I_LABELS.get(
                        entry.key.lower(), entry.key.replace("-", " ").title()
                    ),
                    _resolve_registration_class(entry),
                )
            )

    asr_entries = get_asr_adapter_registry().entries()
    asr_by_key = {entry.key: entry for entry in asr_entries}
    asr: list[dict[str, Any]] = []
    for preferred_asr in ("sherpa_onnx", "vosk"):
        entry = asr_by_key.get(preferred_asr)
        if entry is not None:
            asr.append(
                _adapter_option(
                    entry.key,
                    entry.label or _ASR_FALLBACK_LABELS.get(entry.key, entry.key),
                    _resolve_registration_class(entry),
                )
            )
    for entry in sorted(
        (item for item in asr_entries if item.key not in {"sherpa_onnx", "vosk"}),
        key=lambda item: item.key.lower(),
    ):
        asr.append(
            _adapter_option(
                entry.key,
                entry.label or _ASR_FALLBACK_LABELS.get(entry.key, entry.key),
                _resolve_registration_class(entry),
            )
        )

    vision_entries = get_vision_adapter_registry().entries()
    vision: list[dict[str, Any]] = [_adapter_option("auto", "跟随 LLM（默认）")]
    for entry in sorted(vision_entries, key=lambda item: item.key.lower()):
        vision.append(
            _adapter_option(
                entry.key,
                entry.label or _VISION_FALLBACK_LABELS.get(entry.key, entry.key),
                _resolve_registration_class(entry),
            )
        )

    return {"asr": asr, "llm": llm, "t2i": t2i, "tts": tts, "vision": vision}


def normalize_t2i_provider(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "comfyui"
    try:
        from ai.t2i.registry import get_t2i_adapter_registry

        registration = get_t2i_adapter_registry().get_registration(raw)
        if registration is not None:
            return registration.key
    except Exception:
        pass
    return raw


def configured_vision_available(api_config: Any) -> bool:
    """Report configured vision availability without exposing AI imports to transport."""
    try:
        from ai.vision.service import configured_vision_available as _configured

        return bool(_configured(api_config))
    except Exception:
        return False


__all__ = [
    "adapter_catalog",
    "claude_messages_endpoint_url",
    "claude_models_endpoint_url",
    "configured_vision_available",
    "normalize_t2i_provider",
]
