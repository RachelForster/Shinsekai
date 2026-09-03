from dataclasses import replace

from ai.llm.template.dialog import DialogTemplateContext
from ai.llm.template.dialog.requirements import (
    RequirementsSection,
    build_requirement_sections,
    build_requirements,
)
from sdk.types import OutputContractPatch, RequirementPatch, RequirementSpec


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
