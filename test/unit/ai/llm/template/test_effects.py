from dataclasses import replace

import pytest

from ai.llm.template.dialog.context import (
    DialogTemplateContext, EffectCatalogContext, EffectCatalogEntry,
)
from ai.llm.template.dialog.sections.effects import EffectCatalogSection
from ai.llm.template.prompts.system import (
    RuntimePromptContext,
    build_runtime_prompt_section,
)
from i18n import tr_in_bundle


AUTHORED_SYSTEM = (
    '  {"speech": "{literal}", "effect": "my field"}\n'
    "Output field contract:\n- camera (string): plugin contract\n"
    "可用音效：\n自定义段落\nRequirements:\n- User rule\n\n  "
)


@pytest.mark.parametrize("language", ["zh_CN", "en", "ja"])
def test_catalog_is_one_runtime_section_and_preserves_authored_text(language):
    translate = lambda key: tr_in_bundle(f"template_gen.{key}", language)
    context = RuntimePromptContext(
        system_template=AUTHORED_SYSTEM,
        user_scenario="Scenario",
        json_reminder="Reminder",
    )
    tree = build_runtime_prompt_section()
    assert tree.render(context) == AUTHORED_SYSTEM + "\nScenario\nReminder"
    selected = replace(
        context,
        effect_catalog=EffectCatalogContext(
            effects=(
                EffectCatalogEntry("letter, sealed letter", "image", ("before", "after")),
                EffectCatalogEntry("{rain}", "audio", ("before", "after", "loop", "stop")),
                EffectCatalogEntry("key", "image_audio", ("before", "after")),
            ),
            translate=translate,
        ),
    )
    result = tree.render(selected)
    assert result == (
        AUTHORED_SYSTEM + "\n\n" + translate("effects_header").strip()
        + f"\n- letter, sealed letter [{translate('effect_type_image')}; before, after]"
        + f"\n- {{rain}} [{translate('effect_type_audio')}; before, after, loop, stop]"
        + f"\n- key [{translate('effect_type_image_audio')}; before, after]"
        + "\nScenario\nReminder"
    )
    disabled = replace(
        tree,
        children=tuple(
            replace(child, enabled=False)
            if isinstance(child, EffectCatalogSection)
            else child
            for child in tree.children
        ),
    )
    assert disabled.render(selected) == tree.render(context)


def test_empty_catalog_does_not_resolve_translations():
    def unreachable(_key):
        pytest.fail("an empty catalog must not load prompt copy")

    context = RuntimePromptContext(
        system_template=AUTHORED_SYSTEM,
        user_scenario="",
        json_reminder="",
        effect_catalog=EffectCatalogContext(translate=unreachable),
    )
    assert build_runtime_prompt_section().render(context) == AUTHORED_SYSTEM


def test_catalog_composes_with_both_dialog_and_runtime_contexts():
    catalog = EffectCatalogContext(
        effects=(EffectCatalogEntry("key", "image", ("before", "after")),),
        translate=lambda key: key,
    )
    dialog = DialogTemplateContext(
        characters=(), translate=lambda key: key, target_voice_name="en", json_reminder=""
    )
    runtime = RuntimePromptContext("system", "scenario", "reminder")
    section = EffectCatalogSection()
    assert section.render(dialog) == section.render(runtime) == ""
    assert section.render(replace(dialog, effect_catalog=catalog)) == section.render(
        replace(runtime, effect_catalog=catalog)
    )
