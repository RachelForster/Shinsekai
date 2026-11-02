from dataclasses import replace

import pytest

from ai.llm.template.dialog import DialogTemplateContext, DialogTemplateSection
from ai.llm.template.dialog.sections.requirements import (
    RequirementsSection,
    build_requirement_sections,
    build_requirements,
)
from sdk.types import OutputContractPatch, OutputFieldSpec, RequirementPatch, RequirementSpec


def make_context(**kwargs):
    return DialogTemplateContext(
        characters=(),
        target_voice_name="Japanese",
        json_reminder="JSON",
        translate=lambda key, **_kwargs: key,
        use_choice=False,
        use_narration=False,
        use_stat=False,
        **kwargs,
    )


def test_rule_nodes_retain_disabled_features_without_rendering_their_text():
    calls = []

    def translate(key, **_kwargs):
        calls.append(key)
        return key

    context = replace(make_context(), translate=translate)
    nodes = {node.id: node for node in build_requirement_sections(context)}

    assert nodes["r_format"].enabled is True
    assert nodes["r_effect"].enabled is False
    assert nodes["r_choice_format"].enabled is False
    assert nodes["r_speech_max_chars"].enabled is False
    assert nodes["r_effect"].render(context) == ""
    assert "r_effect" not in calls

    text = RequirementsSection("requirements").render(context)
    assert "- r_format\n" in text
    assert "- r_effect\n" not in text
    assert "r_effect" not in calls
    assert "r_choice_format" not in calls

    enabled = replace(context, use_effect=True, max_speech_chars=80)
    enabled_nodes = {node.id: node for node in build_requirement_sections(enabled)}
    assert nodes.keys() == enabled_nodes.keys()
    assert enabled_nodes["r_effect"].enabled is True
    assert enabled_nodes["r_speech_max_chars"].enabled is True
    assert "- r_effect\n" in RequirementsSection("requirements").render(enabled)


def test_patching_disabled_feature_is_noop_but_explicit_addition_is_supported():
    patch = OutputContractPatch(
        id="rules",
        target_contract="default.dialog.v1",
        requirement_patches={
            "r_effect": RequirementPatch("replace", "must stay absent"),
            "r_speech": RequirementPatch("remove"),
        },
    )
    context = make_context(output_contract_patches=(patch,))
    requirements = {rule.id: rule for rule in build_requirements(context)}
    assert "r_effect" not in requirements
    assert "r_speech" not in requirements

    addition = replace(
        patch,
        add_requirements=(RequirementSpec("r_effect", "plugin effect", 11),),
    )
    added_context = replace(context, output_contract_patches=(addition,))
    rules = build_requirements(added_context)
    assert [(rule.id, rule.text) for rule in rules[:2]] == [
        ("r_format", "r_format"),
        ("r_effect", "plugin effect"),
    ]
    assert "- plugin effect\n" in RequirementsSection("requirements").render(
        added_context
    )


def test_disabled_requirement_group_skips_translation_and_patch_evaluation():
    def unreachable(*_args, **_kwargs):
        raise AssertionError("disabled group must not build or translate rules")

    context = replace(make_context(), translate=unreachable)
    assert RequirementsSection("requirements", enabled=False).render(context) == ""


@pytest.mark.parametrize(
    "field,example,other_field,other_example",
    [
        ("effect", "json_line_effect", "translate", "json_line_trans"),
        ("translate", "json_line_trans", "effect", "json_line_effect"),
    ],
)
def test_remove_only_patch_projects_to_rules_and_json_example(
    field, example, other_field, other_example
):
    patch = OutputContractPatch(
        id="remove", target_contract="default.dialog.v1", remove_fields=(field,)
    )
    context = make_context(
        use_effect=True, use_llm_translation=True, output_contract_patches=(patch,)
    )
    root = DialogTemplateSection()
    text = root.render(context)
    rules = {rule.id for rule in build_requirements(context)}

    assert f"r_{field}" not in rules
    assert f"- r_{field}\n" not in text
    assert example not in text
    assert f"- {field}: Do not include this field in the output.\n" in text
    assert f"r_{other_field}" in rules
    assert other_example in text
    assert "- r_speech\n" in text
    assert "Output field contract" not in text

    unpatched = root.render(replace(context, output_contract_patches=()))
    assert example in unpatched
    assert f"- r_{field}\n" in unpatched
    assert "Do not include this field" not in unpatched
    assert root.render(context) == text


@pytest.mark.parametrize("media_mode,selection", [("indexed", "sprite"), ("semantic", "vibe")])
def test_removing_protected_or_unavailable_fields_leaves_prompt_unchanged(media_mode, selection):
    context = make_context(media_selection_mode=media_mode)
    patch = OutputContractPatch(
        id="remove", target_contract="default.dialog.v1",
        remove_fields=("character_name", "speech", selection, "effect", "translate", "missing"),
    )
    root = DialogTemplateSection()
    assert root.render(replace(context, output_contract_patches=(patch,))) == root.render(context)


@pytest.mark.parametrize("remove_priority,add_priority,removed", [(10, 20, False), (20, 10, True)])
def test_field_removal_uses_final_patch_state(remove_priority, add_priority, removed):
    removal = OutputContractPatch(
        id="remove", target_contract="default.dialog.v1", priority=remove_priority,
        remove_fields=("effect",),
    )
    addition = OutputContractPatch(
        id="add", target_contract="default.dialog.v1", priority=add_priority,
        add_fields=(OutputFieldSpec("effect", description="Plugin effect guidance."),),
        add_requirements=(RequirementSpec("r_effect", "Plugin effect rule."),),
    )
    context = make_context(use_effect=True, output_contract_patches=(removal, addition))
    text = DialogTemplateSection().render(context)
    assert ("Do not include this field" in text) is removed
    assert ("json_line_effect" in text) is not removed
    assert ("Plugin effect guidance." in text) is not removed
    assert ("Plugin effect rule." in text) is not removed


def test_rule_addition_cannot_restore_a_removed_field():
    patch = OutputContractPatch(
        id="remove", target_contract="default.dialog.v1", remove_fields=("effect",),
        add_requirements=(RequirementSpec("r_effect", "Contradictory effect rule."),),
    )
    context = make_context(use_effect=True, output_contract_patches=(patch,))
    text = DialogTemplateSection().render(context)
    assert "Contradictory effect rule." not in text
    assert "Do not include this field" in text


def test_added_then_removed_plugin_field_leaves_no_guidance():
    addition = OutputContractPatch(
        id="add", target_contract="default.dialog.v1",
        add_fields=(OutputFieldSpec("camera", description="Camera framing."),),
    )
    removal = OutputContractPatch(
        id="remove", target_contract="default.dialog.v1", remove_fields=("camera",),
    )
    root = DialogTemplateSection()
    context = make_context()
    assert root.render(replace(context, output_contract_patches=(addition, removal))) == root.render(context)
    assert "Camera framing." in root.render(replace(context, output_contract_patches=(removal, addition)))
