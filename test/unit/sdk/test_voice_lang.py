"""Unit tests for shared TTS voice language normalization and auto-resolution."""

from __future__ import annotations

from sdk.voice_lang import (
    VOICE_LANG_AUTO,
    infer_language_from_text,
    normalize_voice_language,
    resolve_character_voice_language,
)


def test_normalize_voice_language_maps_auto_and_aliases() -> None:
    assert normalize_voice_language("auto") == VOICE_LANG_AUTO
    assert normalize_voice_language(" 自动 ") == VOICE_LANG_AUTO
    assert normalize_voice_language("自動") == VOICE_LANG_AUTO
    assert normalize_voice_language("all_zh") == "zh"
    assert normalize_voice_language("zh-CN") == "zh"
    assert normalize_voice_language("Japanese") == "ja"
    assert normalize_voice_language("en_US") == "en"
    assert normalize_voice_language("zh_HK") == "yue"
    assert normalize_voice_language("") == ""


def test_infer_language_from_text_detects_kana_cjk_hangul_and_latin() -> None:
    assert infer_language_from_text("おはようございます") == "ja"
    assert infer_language_from_text("今天天气真不错") == "zh"
    assert infer_language_from_text("안녕하세요") == "ko"
    assert infer_language_from_text("Hello there") == "en"
    assert infer_language_from_text("123...") == ""


def test_resolve_character_voice_language_preserves_explicit_and_resolves_auto() -> None:
    assert resolve_character_voice_language("ja", prompt_lang="zh") == "ja"
    assert resolve_character_voice_language("zh_CN", prompt_lang="en") == "zh_CN"

    assert resolve_character_voice_language("auto", prompt_lang="all_zh") == "zh"
    assert resolve_character_voice_language("auto", prompt_lang="japanese") == "ja"
    assert resolve_character_voice_language("auto", prompt_lang="en") == "en"
    assert (
        resolve_character_voice_language("auto", prompt_lang="", prompt_text="你好，请问需要帮忙吗？")
        == "zh"
    )
    assert (
        resolve_character_voice_language("auto", prompt_lang="", prompt_text="", speech_text="Let's go")
        == "en"
    )
    assert resolve_character_voice_language("auto", prompt_lang="", prompt_text="", speech_text="") == "ja"
