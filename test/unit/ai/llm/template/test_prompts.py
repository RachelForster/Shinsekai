import pytest

from ai.llm.template.prompts import (
    RuntimePromptContext,
    UserPromptContext,
    build_runtime_prompt_section,
    build_user_prompt_section,
)
from application.chat.templates import _compose_for_llm, _compose_runtime_template


def test_user_prompt_preserves_literal_text_and_is_reusable():
    tree = build_user_prompt_section()
    context = UserPromptContext(
        user_input='  {"question": "{name}"}\n继续  ',
        prefix="Relevant memory",
        suffix="Keep it brief",
    )

    assert tree.render(context) == (
        'Relevant memory\n\n  {"question": "{name}"}\n继续  \n\nKeep it brief'
    )
    assert tree.render(UserPromptContext("second turn")) == "second turn"
    assert (
        build_user_prompt_section("\n").render(
            UserPromptContext(
                "text",
                prefix="[local time]",
            )
        )
        == "[local time]\ntext"
    )


@pytest.mark.parametrize(
    "scenario,system,expected",
    [
        (" scenario ", " system ", "scenario\n\nsystem"),
        ("", " system ", "system"),
        (" scenario ", "", "scenario"),
        ("\n", " ", ""),
        (None, None, ""),
        ('{"literal": "{value}"}', "rules", '{"literal": "{value}"}\n\nrules'),
    ],
)
def test_generation_prompt_preserves_existing_composition(scenario, system, expected):
    assert _compose_for_llm(scenario, system) == expected


def test_runtime_tree_inherits_context_and_places_reminder_last():
    context = RuntimePromptContext("rules", "opening scene", "JSON")
    assert (
        build_runtime_prompt_section().render(context) == "rules\nopening scene\nJSON"
    )


@pytest.mark.parametrize(
    "system,scenario,expected",
    [
        (" rules \n", " scene \n", " rules\nscene\nJSON\n"),
        (" ", "scene", "scene\nJSON\n"),
        (None, "  ", "你扮演一个RPG系统。\nJSON\n"),
    ],
)
def test_runtime_prompt_retains_defaults_whitespace_and_terminator(
    monkeypatch,
    system,
    scenario,
    expected,
):
    monkeypatch.setattr(
        "application.chat.templates.json_format_reminder", lambda: "JSON"
    )
    assert _compose_runtime_template(system, scenario) == expected
