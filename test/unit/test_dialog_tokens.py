"""Unit tests for dialog token matching functions and alias constants."""

import pytest

from core.messaging.dialog_tokens import (
    BGM,
    BGM_ALIASES,
    CG,
    CG_ALIASES,
    CHOICE,
    CHOICE_ALIASES,
    COT,
    COT_ALIASES,
    NARR,
    NARR_ALIASES,
    SCENE,
    SCENE_ALIASES,
    STAT,
    STAT_ALIASES,
    SYSTEM_DIALOG_TTS_ALIASES,
    SYSTEM_UI_SKIP,
    match_bgm_name,
    match_cg_name,
    match_choice_name,
    match_cot_name,
    match_scene_name,
    match_stat_name,
    normalize_character_name,
)


class TestNormalizeCharacterName:
    def test_ascii_lowercase_to_upper(self):
        assert normalize_character_name("cot") == COT
        assert normalize_character_name("narr") == NARR
        assert normalize_character_name("choice") == CHOICE
        assert normalize_character_name("stat") == STAT
        assert normalize_character_name("scene") == SCENE
        assert normalize_character_name("bgm") == BGM
        assert normalize_character_name("cg") == CG

    def test_uppercase_preserved(self):
        assert normalize_character_name("COT") == COT
        assert normalize_character_name("NARR") == NARR

    def test_mixed_case_normalized(self):
        assert normalize_character_name("Cot") == COT
        assert normalize_character_name("Narr") == NARR

    def test_chinese_names_untouched(self):
        assert normalize_character_name("旁白") == "旁白"
        assert normalize_character_name("思维链") == "思维链"

    def test_custom_names_untouched(self):
        assert normalize_character_name("Alice") == "Alice"
        assert normalize_character_name("狛枝凪斗") == "狛枝凪斗"

    def test_none_returns_empty(self):
        assert normalize_character_name(None) == ""

    def test_empty_returns_empty(self):
        assert normalize_character_name("") == ""

    def test_whitespace_stripped(self):
        assert normalize_character_name("  cot  ") == COT


class TestMatchCOT:
    def test_new_code(self):
        assert match_cot_name("COT") is True

    def test_chinese_alias(self):
        assert match_cot_name("思维链") is True

    def test_lowercase(self):
        assert match_cot_name("cot") is True

    def test_non_matching(self):
        assert match_cot_name("NARR") is False
        assert match_cot_name("Alice") is False


class TestMatchBGM:
    def test_lowercase(self):
        assert match_bgm_name("bgm") is True

    def test_uppercase(self):
        assert match_bgm_name("BGM") is True

    def test_casefold(self):
        assert match_bgm_name("Bgm") is True

    def test_non_matching(self):
        assert match_bgm_name("music") is False

    def test_chinese_not_allowed(self):
        # bgm does NOT have Chinese alias in BGM_ALIASES
        assert "背景音乐" not in BGM_ALIASES


class TestMatchCG:
    def test_uppercase(self):
        assert match_cg_name("CG") is True

    def test_lowercase(self):
        assert match_cg_name("cg") is True

    def test_non_matching(self):
        assert match_cg_name("illust") is False


class TestMatchChoice:
    def test_code(self):
        assert match_choice_name("CHOICE") is True

    def test_chinese(self):
        assert match_choice_name("选项") is True

    def test_lowercase_code(self):
        assert match_choice_name("choice") is True

    def test_non_matching(self):
        assert match_choice_name("NARR") is False


class TestMatchStat:
    def test_code(self):
        assert match_stat_name("STAT") is True

    def test_chinese(self):
        assert match_stat_name("数值") is True

    def test_non_matching(self):
        assert match_stat_name("SCENE") is False


class TestMatchScene:
    def test_code(self):
        assert match_scene_name("SCENE") is True

    def test_chinese(self):
        assert match_scene_name("场景") is True

    def test_non_matching(self):
        assert match_scene_name("BG") is False


class TestAliasSets:
    def test_cot_aliases_contain_code_and_chinese(self):
        assert COT in COT_ALIASES
        assert "思维链" in COT_ALIASES

    def test_narr_aliases(self):
        assert NARR in NARR_ALIASES
        assert "旁白" in NARR_ALIASES

    def test_choice_aliases(self):
        assert CHOICE in CHOICE_ALIASES
        assert "选项" in CHOICE_ALIASES

    def test_stat_aliases(self):
        assert STAT in STAT_ALIASES
        assert "数值" in STAT_ALIASES

    def test_scene_aliases(self):
        assert SCENE in SCENE_ALIASES
        assert "场景" in SCENE_ALIASES

    def test_system_dialog_tts_covers_narr_choice_stat_scene(self):
        combined = NARR_ALIASES | CHOICE_ALIASES | STAT_ALIASES | SCENE_ALIASES
        assert SYSTEM_DIALOG_TTS_ALIASES == combined

    def test_system_ui_skip_excludes_narr(self):
        assert NARR not in SYSTEM_UI_SKIP
        assert "旁白" not in SYSTEM_UI_SKIP

    def test_system_ui_skip_includes_all_others(self):
        for name in ("COT", "思维链", "CHOICE", "选项", "STAT", "数值", "SCENE", "场景", "bgm", "cg", "CG"):
            assert name in SYSTEM_UI_SKIP, f"{name} should be in SYSTEM_UI_SKIP"
