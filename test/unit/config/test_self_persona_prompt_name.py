"""Unit tests for using built-in self-persona display_name with identity note in prompts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.llm.template.dialog.sections.player import (
    format_self_persona_prompt,
    strip_self_persona_block,
)
from ai.llm.template_generator import TemplateGenerator
from config.schema import (
    Character,
    RelationEdge,
    RelationGraph,
    RelationNode,
    SELF_PERSONA_NAME,
    Sprite,
    build_default_self_persona,
    resolve_character_by_prompt_name,
    resolve_character_prompt_name,
)


class _FakeConfigManager:
    def __init__(self, characters: list[Character], ui_language: str = "zh_CN"):
        self.config = SimpleNamespace(
            characters=characters,
            system_config=SimpleNamespace(voice_language="ja", ui_language=ui_language),
        )

    def get_character_by_name(self, name: str):
        target = name.strip().casefold()
        found = next(
            (c for c in self.config.characters if c.name.strip().casefold() == target),
            None,
        )
        if found is not None:
            return found
        if name.strip() == SELF_PERSONA_NAME:
            return build_default_self_persona()
        return None


def _named_self(display_name: str = "浅羽", setting: str = "表面冷静的调查员。") -> Character:
    return build_default_self_persona().model_copy(
        update={
            "display_name": display_name,
            "character_setting": setting,
            "sprites": [Sprite(path="data/sprite/__self__/idle.png")],
            "emotion_tags": "立绘 1：平静\n",
        }
    )


def test_resolve_prompt_name_and_reverse_lookup() -> None:
    self_char = _named_self("浅羽")
    mika = Character(name="Mika", color="#fff", sprite_prefix="mika")
    colliding = Character(name="浅羽", color="#0ff", sprite_prefix="asaba")

    assert resolve_character_prompt_name(self_char) == "浅羽"
    assert resolve_character_prompt_name(self_char, colliding_names=["Mika", SELF_PERSONA_NAME]) == "浅羽"
    assert resolve_character_prompt_name(self_char, colliding_names=["浅羽", SELF_PERSONA_NAME]) == SELF_PERSONA_NAME
    assert resolve_character_prompt_name(mika, colliding_names=["浅羽"]) == "Mika"

    cfg = _FakeConfigManager([self_char, mika])
    assert resolve_character_by_prompt_name(cfg, "浅羽") is self_char
    assert resolve_character_by_prompt_name(cfg, SELF_PERSONA_NAME) is self_char
    assert resolve_character_by_prompt_name(cfg, "mika") is mika
    assert resolve_character_by_prompt_name(cfg, "unknown") is None

    # Canonical character with the same name always takes precedence over 自设.display_name
    cfg_collision = _FakeConfigManager([self_char, colliding])
    assert resolve_character_by_prompt_name(cfg_collision, "浅羽") is colliding


def test_template_generator_uses_display_name_for_npc_cast_and_supporting_brief(monkeypatch) -> None:
    mika = Character(name="Mika", color="#fff", sprite_prefix="mika", character_setting="活泼的青梅竹马。")
    self_char = _named_self("浅羽", "表面冷静的调查员。")
    cfg = _FakeConfigManager([self_char, mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)

    prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert "出场人物有：Mika，浅羽" in prompt
    assert "浅羽有1张立绘：" in prompt
    assert "以下是浅羽的角色设定：\n该人物是用户自设。\n表面冷静的调查员。" in prompt
    assert "character_name 字段只能是以下之一：Mika，浅羽" in prompt
    assert "不要将「" not in prompt
    assert "「自设」" not in prompt

    # Empty setting still outputs identity note under display_name
    empty_named_self = _named_self("浅羽", "")
    cfg_empty = _FakeConfigManager([empty_named_self, mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_empty)
    compact_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        primary_characters=["Mika"],
        player_character="",
    )
    assert "次要角色简介：\n浅羽：该人物是用户自设。" in compact_prompt


def test_template_generator_uses_display_name_for_player_and_background_only(monkeypatch) -> None:
    mika = Character(name="Mika", color="#fff", sprite_prefix="mika", character_setting="活泼的青梅竹马。")
    self_char = _named_self("浅羽", "随身带着旧怀表。")
    cfg = _FakeConfigManager([self_char, mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)

    # User-controlled player
    user_player_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        player_character=SELF_PERSONA_NAME,
        allow_player_dialogue=False,
    )
    assert "用户控制的主控人物：浅羽\n该人物是用户自设。\n随身带着旧怀表。" in user_player_prompt
    assert '{"character_name":"浅羽","sprite":"01","speech":""}' in user_player_prompt
    assert "涉及主控的旁白应明确写出浅羽" in user_player_prompt
    assert "主控人物：自设" not in user_player_prompt

    # AI-controlled player
    ai_player_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        player_character=SELF_PERSONA_NAME,
        allow_player_dialogue=True,
    )
    assert "主控人物：浅羽\n该人物是用户自设。\n随身带着旧怀表。" in ai_player_prompt
    assert "允许 AI 为浅羽编写新的台词和回答" in ai_player_prompt

    # Background-only with setting + name
    bg_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika"],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert "人物名称：浅羽（该人物是用户自设）\n随身带着旧怀表。" in bg_prompt
    assert "不要将「浅羽」作为独立台词角色输出" in bg_prompt

    # Background-only with name only (empty setting)
    cfg_name_only = _FakeConfigManager([_named_self("浅羽", ""), mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_name_only)
    bg_name_only, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika"],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert "人物名称：浅羽（该人物是用户自设）" in bg_name_only
    assert "不要将「浅羽」作为独立台词角色输出" in bg_name_only


def test_template_generator_collision_fallback_and_relation_rewriting(monkeypatch) -> None:
    mika = Character(
        name="Mika",
        color="#fff",
        sprite_prefix="mika",
        character_setting="朋友",
        relation_graph=RelationGraph(
            nodes=[RelationNode(key="Mika"), RelationNode(key=SELF_PERSONA_NAME)],
            edges=[RelationEdge(source="Mika", target=SELF_PERSONA_NAME, temperature=5, content="信赖伙伴")],
        ),
    )
    self_char = _named_self("浅羽", "调查员").model_copy(
        update={
            "relation_graph": RelationGraph(
                nodes=[RelationNode(key=SELF_PERSONA_NAME), RelationNode(key="Mika")],
                edges=[RelationEdge(source=SELF_PERSONA_NAME, target="Mika", temperature=4, content="同窗")],
            ),
        }
    )
    cfg = _FakeConfigManager([self_char, mika])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)

    rel_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Mika", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert "浅羽的关系图谱：\n浅羽对Mika：同窗(亲密度：4)" in rel_prompt
    assert "Mika的关系图谱：\nMika对浅羽：信赖伙伴(亲密度：5)" in rel_prompt
    assert "自设的关系图谱" not in rel_prompt

    # Collision with another character literally named 浅羽 falls back safely to 自设
    other_asaba = Character(name="浅羽", color="#0ff", sprite_prefix="other", character_setting="同名NPC")
    cfg_collision = _FakeConfigManager([self_char, other_asaba])
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg_collision)
    collision_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["浅羽", SELF_PERSONA_NAME],
        "",
        False,
        False,
        False,
        player_character="",
    )
    assert "出场人物有：浅羽，自设" in collision_prompt
    assert "以下是自设的角色设定：\n该人物是用户自设。\n调查员" in collision_prompt


@pytest.mark.parametrize(
    ("locale", "display_name", "expected_line", "expected_prohibition"),
    [
        ("zh_CN", "浅羽", "人物名称：浅羽（该人物是用户自设）", "不要将「浅羽」作为独立台词角色输出"),
        ("en", "Takina", "Character name: Takina (this character is the user's self-persona)", 'do not output "Takina" as a standalone speaking character'),
        ("ja", "タキナ", "キャラクター名：タキナ（この人物はユーザーの自設キャラクターです）", "「タキナ」を独立した発話キャラクターとして出力しないでください"),
    ],
)
def test_multilocale_self_persona_block_and_strip(
    locale: str,
    display_name: str,
    expected_line: str,
    expected_prohibition: str,
) -> None:
    block = format_self_persona_prompt("Setting text", locale=locale, display_name=display_name)
    assert expected_line in block
    assert expected_prohibition in block
    stripped = strip_self_persona_block(f"Prefix.\n\n{block}Suffix.")
    assert stripped == "Prefix.\n\nSuffix."

    unnamed_block = format_self_persona_prompt("Setting text", locale=locale)
    assert strip_self_persona_block(f"Prefix.\n\n{unnamed_block}Suffix.") == "Prefix.\n\nSuffix."
