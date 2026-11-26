"""Unit tests for three-locale dialog prompts referencing self-persona by ID."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.llm.template.dialog.sections.player import (
    format_self_persona_prompt,
    player_runtime_prompt,
    strip_self_persona_block,
)
from ai.llm.template_generator import TemplateGenerator
from config.schema import Character, SELF_PERSONA_ID, SELF_PERSONA_NAME, SELF_PERSONA_SPRITE_PREFIX


def _fake_config_manager(*, locale: str, self_char: Character, characters: list[Character]) -> SimpleNamespace:
    def _get_by_name(name: str):
        for item in characters:
            if item.name == name:
                return item
        if name == SELF_PERSONA_NAME:
            return self_char
        return None

    return SimpleNamespace(
        config=SimpleNamespace(
            characters=characters,
            system_config=SimpleNamespace(ui_language=locale, voice_language="ja"),
        ),
        get_self_persona=lambda: self_char,
        get_character_by_name=_get_by_name,
        get_background_by_name=lambda _name: None,
    )


@pytest.mark.parametrize(
    ("locale", "expected_profile", "forbidden_profile", "expected_note", "expected_bg_named"),
    [
        (
            "zh_CN",
            "以下是浅羽的角色设定：",
            "以下是自设的角色设定：",
            "该人物是用户自设。",
            "人物名：浅羽（该人物是用户自设。）",
        ),
        (
            "en",
            "Profile for 浅羽:",
            "Profile for 自设:",
            "This character is the user's self-persona.",
            "Character name: 浅羽 (This character is the user's self-persona.)",
        ),
        (
            "ja",
            "浅羽の設定：",
            "自設の設定：",
            "この人物はユーザーの自設です。",
            "キャラクター名：浅羽（この人物はユーザーの自設です。）",
        ),
    ],
)
def test_renamed_self_persona_prompts_use_actual_name_and_identity_note(
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
    expected_profile: str,
    forbidden_profile: str,
    expected_note: str,
    expected_bg_named: str,
) -> None:
    self_char = Character(
        id=SELF_PERSONA_ID,
        name="浅羽",
        color="#89b4fa",
        sprite_prefix=SELF_PERSONA_SPRITE_PREFIX,
        character_setting="Observatory astronomy student.",
        is_builtin=True,
        pinned=True,
        undeletable=True,
    )
    mika = Character(name="Mika", color="#ffffff", sprite_prefix="mika", character_setting="Class representative.")
    fake_cfg = _fake_config_manager(locale=locale, self_char=self_char, characters=[self_char, mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", fake_cfg)
    monkeypatch.setattr("ai.llm.template_generator._format_llm_tools_block", lambda: "")

    generator = TemplateGenerator(output_contract_patches=[])
    generator.resolve_chat_template_characters = lambda names: [  # type: ignore[method-assign]
        (item.name, item) for item in (self_char, mika) if item.name in names
    ]

    cast_template, _ = generator.generate_chat_template(
        ["浅羽", "Mika"],
        "",
        False,
        False,
        False,
    )
    assert expected_profile in cast_template
    assert forbidden_profile not in cast_template
    assert expected_note in cast_template

    bg_template, _ = generator.generate_chat_template(
        ["Mika"],
        "",
        False,
        False,
        False,
    )
    assert expected_bg_named in bg_template
    assert "Observatory astronomy student." in bg_template


def test_strip_self_persona_block_and_runtime_cast_override_across_locales() -> None:
    for locale in ("zh_CN", "en", "ja"):
        default_block = format_self_persona_prompt("Quiet reader.", locale=locale, name=SELF_PERSONA_NAME)
        named_block = format_self_persona_prompt("Quiet reader.", locale=locale, name="浅羽")
        assert "Quiet reader." in default_block
        assert "浅羽" in named_block

        sample_legacy = f"Intro line.\n\n{default_block}\nOutro line."
        assert strip_self_persona_block(sample_legacy) == "Intro line.\n\nOutro line."

        sample_named = f"Intro line.\n\n{named_block}\nOutro line."
        assert strip_self_persona_block(sample_named) == "Intro line.\n\nOutro line."

    self_char = Character(
        id=SELF_PERSONA_ID,
        name="浅羽",
        color="#89b4fa",
        sprite_prefix=SELF_PERSONA_SPRITE_PREFIX,
        character_setting="Quiet reader.",
        is_builtin=True,
        pinned=True,
        undeletable=True,
    )
    mika = Character(name="Mika", color="#ffffff", sprite_prefix="mika")
    fake_cfg = _fake_config_manager(locale="zh_CN", self_char=self_char, characters=[self_char, mika])

    runtime_block = player_runtime_prompt(
        fake_cfg,
        "",
        allow_dialogue=True,
        read_speech=False,
        media_selection_mode="indexed",
        character_names=["浅羽", "Mika"],
    )
    assert "「浅羽」（用户自设）已作为独立出场角色参与本次对话" in runtime_block
