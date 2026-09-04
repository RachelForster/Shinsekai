"""JSON example and patch-compatible field contract."""

import json
from dataclasses import dataclass

from sdk.types import OutputFieldSpec

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from ..patches import apply_field_patches


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


def _build_field_contract_section(
    context: DialogTemplateContext,
) -> TextSection[DialogTemplateContext]:
    fields = _build_fields(context)
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
    )
    return TextSection(
        "fields",
        enabled=bool(fields),
        text="\nOutput field contract:\n",
        children=lines,
    )


@dataclass(frozen=True)
class JsonSchemaSection(Section[DialogTemplateContext]):
    id: str = "json_schema"

    def _resolve_children(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
        translate = context.translate
        generated = (
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
            _build_field_contract_section(context),
        )
        return *generated, *self.children
