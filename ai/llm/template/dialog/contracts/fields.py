"""Build the patch-compatible dialog field contract section."""

from sdk.types import OutputFieldSpec

from ...core import TextSection
from ..context import DialogTemplateContext
from .patches import apply_field_patches


def build_fields(context: DialogTemplateContext) -> dict[str, OutputFieldSpec]:
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
        ("sprite", "r_sprite", True, True, {}),
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
    return apply_field_patches(fields, context.output_contract_patches)


def build_field_contract_section(
    context: DialogTemplateContext,
) -> TextSection[DialogTemplateContext]:
    fields = build_fields(context)
    lines = []
    for output_field in fields.values():
        requirement = "required" if output_field.required else "optional"
        aliases = TextSection(
            "aliases",
            enabled=bool(output_field.aliases),
            text=f" Aliases: {', '.join(output_field.aliases)}.",
        )
        lines.append(
            TextSection(
                output_field.key,
                text=f"- {output_field.key} ({output_field.type}, {requirement}): "
                f"{output_field.description}",
                children=(
                    aliases,
                    TextSection("line_end", text="\n"),
                ),
            )
        )
    return TextSection(
        "fields",
        enabled=bool(fields),
        text="\nOutput field contract:\n",
        children=tuple(lines),
    )
