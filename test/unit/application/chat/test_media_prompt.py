from copy import deepcopy
from types import SimpleNamespace

import pytest

from ai.llm.template.dialog.context import DialogTemplateContext
from ai.llm.template.dialog.sections.json_schema import JsonSchemaSection
from ai.llm.template.integrations.localization import translate_template
from application.chat.media_prompt import align_history_media_prompt


@pytest.fixture
def config():
    character = SimpleNamespace(
        sprites=[{"path": "calm.webp"}],
        emotion_tags="sprite 01: calm",
    )
    return SimpleNamespace(
        get_character_by_name=lambda name: character if name == "Alice" else None,
        get_background_by_name=lambda name: SimpleNamespace(
            sprites=[{"path": "room.webp"}],
            bg_tags="sprite 01: room",
            bgm_list=["quiet.wav"],
            bgm_tags="sprite 01: quiet",
        ),
    )


def saved_messages(mode):
    context = DialogTemplateContext(
        characters=(),
        translate=translate_template,
        target_voice_name="Japanese",
        json_reminder="",
        media_selection_mode=mode,
    )
    return [
        {
            "role": "system",
            "content": "Original story and persona\n"
            + JsonSchemaSection().render(context),
        },
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "saved reply"},
    ]


@pytest.mark.parametrize(
    "old_mode,new_mode,field",
    [
        ("semantic", "indexed", "sprite"),
        ("indexed", "semantic", "vibe"),
    ],
)
def test_restored_prompt_uses_active_media_rules_without_replacing_history(
    config,
    old_mode,
    new_mode,
    field,
):
    messages = saved_messages(old_mode)
    original = deepcopy(messages)
    result = align_history_media_prompt(
        messages,
        config=config,
        character_names=["Alice"],
        mode=new_mode,
        background_name="room",
    )
    assert messages == original
    assert result[1:] == original[1:]
    assert result[0]["content"].startswith(original[0]["content"])
    override = result[0]["content"][len(original[0]["content"]) :]
    assert f"Use the `{field}` field" in override
    assert translate_template(f"r_{field}") in override
    for tag in ("sprite 01: calm", "sprite 01: room", "sprite 01: quiet"):
        assert (tag in override) == (new_mode == "indexed")
    assert (
        align_history_media_prompt(
            result,
            config=config,
            character_names=["Alice"],
            mode=new_mode,
            background_name="room",
        )
        == result
    )
    assert (
        align_history_media_prompt(
            result,
            config=config,
            character_names=["Alice"],
            mode=old_mode,
        )
        == original
    )


def test_matching_and_custom_prompts_are_unchanged(config):
    for messages in (
        saved_messages("indexed"),
        [{"role": "system", "content": "Custom instructions mentioning vibe"}],
    ):
        assert (
            align_history_media_prompt(
                messages,
                config=config,
                character_names=["Alice"],
                mode="indexed",
            )
            == messages
        )
