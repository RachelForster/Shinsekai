"""Shared normalization and character-reference resolution for TTS voice language."""

from __future__ import annotations

import re

VOICE_LANG_AUTO = "auto"

_AUTO_TOKENS = frozenset({"auto", "自动", "自動"})

_VOICE_LANGUAGE_ALIASES: dict[str, str] = {
    "all_ja": "ja",
    "all_ko": "ko",
    "all_yue": "yue",
    "all_zh": "zh",
    "cantonese": "yue",
    "chinese": "zh",
    "cht": "yue",
    "cmn": "zh",
    "cn": "zh",
    "en": "en",
    "en_gb": "en",
    "en_us": "en",
    "english": "en",
    "ja": "ja",
    "ja_jp": "ja",
    "japanese": "ja",
    "jp": "ja",
    "ko": "ko",
    "ko_kr": "ko",
    "korean": "ko",
    "yue": "yue",
    "yue_hk": "yue",
    "zh": "zh",
    "zh_cn": "zh",
    "zh_hk": "yue",
    "zh_tw": "zh",
    "zh_yue": "yue",
    "中文": "zh",
    "日文": "ja",
    "日语": "ja",
    "日本語": "ja",
    "汉语": "zh",
    "粤语": "yue",
    "粵語": "yue",
    "英文": "en",
    "英语": "en",
    "韩文": "ko",
    "韩语": "ko",
}

_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def normalize_voice_language(raw: str | None) -> str:
    """Normalize explicit or alias voice language codes (preserving ``auto``)."""
    clean = str(raw or "").strip()
    if not clean:
        return ""
    lowered = clean.lower().replace("-", "_")
    if lowered in _AUTO_TOKENS:
        return VOICE_LANG_AUTO
    if lowered in _VOICE_LANGUAGE_ALIASES:
        return _VOICE_LANGUAGE_ALIASES[lowered]
    return lowered


def infer_language_from_text(text: str | None) -> str:
    """Infer short speech language code (``ja``/``zh``/``ko``/``en``) from sample text."""
    sample = str(text or "").strip()
    if not sample:
        return ""
    if _KANA_RE.search(sample):
        return "ja"
    if _HAN_RE.search(sample):
        return "zh"
    if _HANGUL_RE.search(sample):
        return "ko"
    if _LATIN_RE.search(sample):
        return "en"
    return ""


def resolve_character_voice_language(
    voice_language: str | None,
    *,
    prompt_lang: str | None = None,
    prompt_text: str | None = None,
    speech_text: str | None = None,
    fallback: str = "ja",
) -> str:
    """Resolve effective target speech language; ``auto`` follows character reference language."""
    raw = str(voice_language or "").strip()
    if normalize_voice_language(raw) != VOICE_LANG_AUTO:
        return raw or fallback

    ref_lang = normalize_voice_language(prompt_lang)
    if ref_lang and ref_lang != VOICE_LANG_AUTO:
        return ref_lang

    from_prompt = infer_language_from_text(prompt_text)
    if from_prompt:
        return from_prompt

    from_speech = infer_language_from_text(speech_text)
    if from_speech:
        return from_speech

    return fallback
