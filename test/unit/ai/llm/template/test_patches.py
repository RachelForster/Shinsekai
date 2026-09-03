from dataclasses import replace

from ai.llm.template.dialog import build_dialog_section
from ai.llm.template.dialog_context import DialogTemplateContext
from ai.llm.template.patches import apply_field_patches, apply_requirement_patches
from sdk.types import (
    FieldPatch,
    OutputContractPatch,
    OutputFieldSpec,
    RequirementPatch,
    RequirementSpec,
)


def patch(id, **kwargs):
    return OutputContractPatch(id=id, target_contract="default.dialog.v1", **kwargs)


def test_fields_preserve_patch_priority_core_fields_aliases_and_inputs():
    fields = {
        key: OutputFieldSpec(key, description="original", required=True)
        for key in ("character_name", "speech", "sprite", "effect")
    }
    early = patch(
        "early",
        priority=10,
        add_fields=(OutputFieldSpec("camera", aliases=("shot",)),),
        field_patches={"speech": FieldPatch(description="early")},
    )
    late = patch(
        "late",
        priority=20,
        remove_fields=("character_name", "speech", "sprite", "effect", "missing"),
        field_patches={
            "speech": FieldPatch(description="late", type="object", required=False),
            "camera": FieldPatch(description="", enum=("close", "wide")),
            "missing": FieldPatch(description="ignored"),
        },
    )
    result = apply_field_patches(fields, (late, early))

    assert list(result) == ["character_name", "speech", "sprite", "camera"]
    assert result["speech"] == OutputFieldSpec("speech", "object", "late", False)
    assert result["camera"].aliases == ("shot",)
    assert "Allowed values: close, wide." in result["camera"].description
    assert fields["speech"].description == "original"
    assert "effect" in fields
    assert apply_field_patches(fields, (late, early)) == result


def test_equal_patch_priorities_keep_input_order_and_additions_override():
    fields = {"speech": OutputFieldSpec("speech", description="base")}
    first = patch("first", field_patches={"speech": FieldPatch(description="first")})
    second = patch("second", field_patches={"speech": FieldPatch(description="second")})
    assert (
        apply_field_patches(fields, (first, second))["speech"].description == "second"
    )
    assert apply_field_patches(fields, (second, first))["speech"].description == "first"

    replacement = OutputFieldSpec("speech", "array", "replacement", aliases=("lines",))
    replace_patch = patch(
        "replace",
        field_patches={"speech": FieldPatch(description="patched")},
        add_fields=(replacement,),
    )
    assert apply_field_patches(fields, (replace_patch,))["speech"] == replacement
    kept = apply_field_patches(
        fields,
        (
            patch(
                "keep",
                field_patches={"speech": FieldPatch(description="", type="", enum=())},
            ),
        ),
    )
    assert kept == fields


def test_requirements_support_all_modes_order_and_reenable_by_addition():
    requirements = [
        RequirementSpec("speech", "base", 10),
        RequirementSpec("remove", "obsolete", 20),
        RequirementSpec("replace", "old", 30),
        RequirementSpec("disabled", "hidden", 40, enabled=False),
    ]
    first = patch(
        "first",
        priority=0,
        requirement_patches={
            "speech": RequirementPatch("append", "after"),
            "remove": RequirementPatch("remove"),
            "replace": RequirementPatch("replace", "new"),
            "disabled": RequirementPatch("replace", "still hidden"),
            "missing": RequirementPatch("append", "ignored"),
        },
    )
    second = patch(
        "second",
        priority=10,
        requirement_patches={"speech": RequirementPatch("prepend", "before")},
        add_requirements=(RequirementSpec("added", "same order", 10),),
    )
    result = apply_requirement_patches(requirements, (second, first))

    assert [(item.id, item.text) for item in result] == [
        ("speech", "before base after"),
        ("added", "same order"),
        ("replace", "new"),
    ]
    assert requirements[0].text == "base" and requirements[1].enabled
    restore = patch("restore", priority=20, add_requirements=(requirements[1],))
    assert [
        item.id
        for item in apply_requirement_patches(
            requirements,
            (first, second, restore),
        )
    ] == ["speech", "added", "remove", "replace"]


def test_render_tree_reuse_does_not_accumulate_patches_or_capture_context():
    context = DialogTemplateContext(
        characters=(),
        translate=lambda key, **_kwargs: f"<{key}>",
        target_voice_name="Japanese",
        json_reminder="JSON",
        output_contract_patches=(
            patch(
                "append",
                requirement_patches={"r_speech": RequirementPatch("append", "ONCE")},
            ),
        ),
    )
    tree = build_dialog_section()
    first = tree.render(context)

    assert first.count("ONCE") == 1
    assert tree.render(context) == first
    assert "ONCE" not in tree.render(replace(context, output_contract_patches=()))
    assert tree.render(replace(context, json_reminder="NEXT")).endswith("NEXT\n")
