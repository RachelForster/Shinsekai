"""JSON example and patch-compatible field contract for dialog output."""

import json
from dataclasses import dataclass

from sdk.types import OutputFieldSpec

from ..core import Section, TextSection
from .context import DialogTemplateContext
from .patches import apply_field_patches


def _json_string_content(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def _build_fields(context: DialogTemplateContext) -> dict[str, OutputFieldSpec]:
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
            {
                "speech_lang_name": context.translate("speech_lang_name"),
            },
        ),
        ("effect", "r_effect", False, context.use_effect, {}),
        (
            "translate",
            "r_translate",
            False,
            context.use_llm_translation,
            {
                "target_voice_name": context.target_voice_name,
            },
        ),
    )
    fields = {
        key: OutputFieldSpec(
            key, description=context.translate(rule, **arguments), required=required
        )
        for key, rule, required, enabled, arguments in definitions
        if enabled
    }
    return apply_field_patches(fields, context.output_contract_patches)


def _render_field_notes(context: DialogTemplateContext) -> str:
    fields = _build_fields(context)
    lines = []
    for field in fields.values():
        required = "required" if field.required else "optional"
        aliases = TextSection(
            "aliases",
            enabled=bool(field.aliases),
            text=f" Aliases: {', '.join(field.aliases)}.",
        ).render(context)
        lines.append(
            TextSection(
                field.key,
                text=f"- {field.key} ({field.type}, {required}): {field.description}{aliases}\n",
            )
        )
    return TextSection(
        "fields",
        enabled=bool(fields),
        text="\nOutput field contract:\n",
        children=tuple(lines),
    ).render(context)


@dataclass(frozen=True)
class JsonSchemaSection(Section[DialogTemplateContext]):
    id: str = "json_schema"

    def render_content(self, context: DialogTemplateContext) -> str:
        translate = context.translate
        tree = Section(
            self.id,
            children=(
                TextSection("head", text=translate("json_head_top")),
                TextSection(
                    "speech",
                    text=translate(
                        "json_speech_line",
                        example=_json_string_content(translate("json_speech_example")),
                    ),
                ),
                TextSection(
                    "effect",
                    enabled=context.use_effect,
                    text=lambda ctx: ctx.translate("json_line_effect"),
                ),
                TextSection(
                    "translation",
                    enabled=context.use_llm_translation,
                    text=lambda ctx: ctx.translate(
                        "json_line_trans",
                        target_voice_name=_json_string_content(ctx.target_voice_name),
                    ),
                ),
                TextSection("foot", text=translate("json_foot")),
                TextSection("fields", text=_render_field_notes),
            ),
        )
        return tree.render(context)
