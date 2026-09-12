from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai.llm.template import Section
from ai.llm.template.dialog import (
    BackgroundSection,
    CharacterSection,
    DialogTemplateContext,
    DialogTemplateSection,
    JsonSchemaSection,
    RequirementsSection,
    build_dialog_section,
)


@pytest.fixture
def context():
    return DialogTemplateContext(
        characters=(
            (
                "Alice",
                SimpleNamespace(
                    sprites=[object()],
                    emotion_tags="happy: 01",
                    character_setting="Alice profile",
                ),
            ),
        ),
        translate=lambda key, **_kwargs: f"<{key}>",
        target_voice_name="Japanese",
        json_reminder="JSON_REMINDER",
        tools_block="TOOLS",
        has_real_background=True,
        background=SimpleNamespace(
            sprites=[object()],
            bg_tags="room: 01",
            bgm_list=[object()],
            bgm_tags="song: 01",
        ),
    )


def test_dialog_root_exposes_the_four_major_section_types(context):
    root = DialogTemplateSection()

    assert [type(child) for child in root.children] == [
        JsonSchemaSection,
        CharacterSection,
        BackgroundSection,
        RequirementsSection,
    ]
    assert isinstance(build_dialog_section(), DialogTemplateSection)
    text = root.render(context)
    boundaries = [
        "<preamble>",
        "<json_head_top>",
        "<sprites_header>",
        "<scene_block_header>",
        "TOOLS",
        "<requirements_header>",
        "<closing>",
        "JSON_REMINDER",
    ]
    assert [text.index(boundary) for boundary in boundaries] == sorted(
        text.index(boundary) for boundary in boundaries
    )


@pytest.mark.parametrize(
    "section_type,markers",
    [
        (JsonSchemaSection, ("<json_head_top>", "Output field contract")),
        (CharacterSection, ("<sprites_header>", "<profile_header>", "Alice profile")),
        (BackgroundSection, ("<scene_block_header>", "room: 01", "song: 01")),
        (
            RequirementsSection,
            ("TOOLS", "<requirements_header>", "<closing>", "JSON_REMINDER"),
        ),
    ],
)
def test_major_sections_can_be_disabled_independently(context, section_type, markers):
    root = DialogTemplateSection()
    configured = replace(
        root,
        children=tuple(
            replace(child, enabled=False) if isinstance(child, section_type) else child
            for child in root.children
        ),
    )

    assert all(marker in root.render(context) for marker in markers)
    assert all(marker not in configured.render(context) for marker in markers)
    assert configured.render(context).startswith("<preamble>")
    assert all(child.enabled for child in root.children)


def test_root_can_be_reused_with_new_context_and_disabled_as_a_whole(context):
    root = DialogTemplateSection()
    original = root.render(context)
    without_background = root.render(replace(context, has_real_background=False))

    assert "<scene_block_header>" in original
    assert "<scene_block_header>" not in without_background
    assert root.render(context) == original

    def unreachable(*_args, **_kwargs):
        pytest.fail("disabled root must not render any section")

    assert (
        replace(root, enabled=False).render(replace(context, translate=unreachable))
        == ""
    )


def test_major_sections_expose_their_runtime_composite_children(context):
    json_children = JsonSchemaSection()._resolve_children(context)
    character_children = CharacterSection()._resolve_children(context)
    background_children = BackgroundSection()._resolve_children(context)
    requirement_children = RequirementsSection()._resolve_children(context)

    assert [child.id for child in json_children] == [
        "head",
        "speech",
        "effect",
        "translation",
        "foot",
        "fields",
    ]
    assert [child.id for child in character_children] == [
        "sprites",
        "profiles",
        "briefs",
    ]
    assert character_children[-1].enabled is False
    assert [child.id for child in background_children] == ["scenes", "music"]
    assert [child.id for child in requirement_children] == [
        "tools",
        "rules",
        "closing",
        "json_reminder",
    ]
    rules = next(child for child in requirement_children if child.id == "rules")
    assert rules.children
    assert all(isinstance(child, Section) for child in rules.children)
    assert any(not child.enabled for child in rules.children)


def test_character_section_uses_briefs_only_for_supporting_characters(context):
    alice = context.characters[0]
    mika = (
        "Mika",
        SimpleNamespace(
            sprites=[],
            emotion_tags="",
            character_brief="Mika brief",
            character_setting="Mika full profile",
        ),
    )
    compact = replace(
        context,
        characters=(alice, mika),
        primary_character_names=frozenset({"Alice"}),
    )

    children = CharacterSection()._resolve_children(compact)
    rendered = CharacterSection().render(compact)

    assert [child.id for child in children] == ["sprites", "profiles", "briefs"]
    assert "Alice profile" in rendered
    assert "Mika brief" in rendered
    assert "Mika full profile" not in rendered


def test_character_section_falls_back_to_setting_when_a_brief_is_missing(context):
    mika = (
        "Mika",
        SimpleNamespace(
            sprites=[],
            emotion_tags="",
            character_setting="Mika fallback profile",
        ),
    )
    compact = replace(
        context,
        characters=(context.characters[0], mika),
        primary_character_names=frozenset({"Alice"}),
    )

    assert "Mika fallback profile" in CharacterSection().render(compact)


def test_semantic_media_mode_uses_vibe_and_omits_numbered_asset_catalogs(context):
    semantic = replace(context, media_selection_mode="semantic")

    rendered = DialogTemplateSection().render(semantic)

    assert "<json_vibe_head_top>" in rendered
    assert "vibe (string, required)" in rendered
    assert "sprite (string, required)" not in rendered
    assert "<r_vibe>" in rendered
    assert "<r_non_vibe>" in rendered
    assert "<r_scene_vibe>" in rendered
    assert "<r_bgm_vibe>" in rendered
    assert "<sprites_header>" not in rendered
    assert "<scene_block_header>" not in rendered
    assert "<bgm_block_header>" not in rendered
    assert "Alice profile" in rendered
