from dataclasses import replace
from types import SimpleNamespace

import pytest

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
