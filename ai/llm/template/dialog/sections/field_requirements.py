"""Only plugin-specific field changes need additional requirement text."""

from sdk.types import OutputFieldSpec
from ...core import TextSection
from ..context import DialogTemplateContext
from ..patches import apply_field_patches


def _base_fields(context: DialogTemplateContext) -> dict[str, OutputFieldSpec]:
    definitions = (
        (
            "character_name",
            "r_cname",
            True,
            True,
            {
                "names": context.names,
                "cot_part": "",
                "fixed_roles": "",
                "opt_scene": "",
                "opt_bgm": "",
                "opt_cg": "",
            },
        ),
        ("sprite", "r_sprite", True, not context.uses_vibe, {}),
        ("vibe", "r_vibe", True, context.uses_vibe, {}),
        (
            "speech",
            "r_speech",
            True,
            True,
            {"speech_lang_name": context.translate("speech_lang_name")},
        ),
        ("effect", "r_effect", False, context.use_effect, {}),
        (
            "translate",
            "r_translate",
            False,
            context.use_llm_translation,
            {"target_voice_name": context.target_voice_name},
        ),
    )
    fields = {
        key: OutputFieldSpec(
            key,
            description=context.translate(rule, **arguments),
            required=required,
        )
        for key, rule, required, enabled, arguments in definitions
        if enabled
    }
    return fields


def _patched_fields(
    context: DialogTemplateContext,
    fields: dict[str, OutputFieldSpec],
) -> dict[str, OutputFieldSpec]:
    selection_field = "vibe" if context.uses_vibe else "sprite"
    return apply_field_patches(
        fields,
        context.output_contract_patches,
        protected_fields=frozenset({"character_name", "speech", selection_field}),
    )


def removed_optional_fields(context: DialogTemplateContext) -> tuple[str, ...]:
    """Resolve removable builtin fields without translating their rule text."""
    if not any(patch.remove_fields for patch in context.output_contract_patches):
        return ()
    base = {
        key: OutputFieldSpec(key)
        for key, enabled in (
            ("effect", context.use_effect),
            ("translate", context.use_llm_translation),
        )
        if enabled
    }
    fields = _patched_fields(context, base)
    return tuple(key for key in base if key not in fields)


def build_field_requirements(
    context: DialogTemplateContext,
) -> TextSection[DialogTemplateContext]:
    if not any(
        patch.field_patches or patch.add_fields or patch.remove_fields
        for patch in context.output_contract_patches
    ):
        return TextSection("fields", enabled=False)
    base = _base_fields(context)
    fields = _patched_fields(context, base)
    lines = tuple(
        TextSection(
            output_field.key,
            text=(
                f"- {output_field.key} ({output_field.type}, "
                f"{'required' if output_field.required else 'optional'}): "
                f"{output_field.description}"
            ),
            children=(
                TextSection(
                    "aliases",
                    enabled=bool(output_field.aliases),
                    text=f" Aliases: {', '.join(output_field.aliases)}.",
                ),
                TextSection("line_end", text="\n"),
            ),
        )
        for output_field in fields.values()
        if output_field != base.get(output_field.key)
    )
    lines += tuple(
        TextSection(key, text=f"- {key}: Do not include this field in the output.\n")
        for key in base
        if key not in fields
    )
    return TextSection(
        "fields",
        priority=180,
        enabled=bool(lines),
        children=lines,
    )
