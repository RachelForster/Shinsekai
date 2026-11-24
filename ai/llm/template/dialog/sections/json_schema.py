"""Illustrative output schema; field rules live in RequirementsSection."""

import json
from dataclasses import dataclass

from core.messaging.formats.registry import resolve_dialog_format
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from .field_requirements import removed_optional_fields


def _json_string_content(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


@dataclass(frozen=True)
class JsonSchemaSection(Section[DialogTemplateContext]):
    id: str = "json_schema"

    def _resolve_children(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
        translate = context.translate
        removed = removed_optional_fields(context)
        format_id = str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()

        if format_id not in (DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID):
            fmt = resolve_dialog_format(format_id)
            custom_hint = fmt.render_schema_hint(
                media_field="vibe" if context.uses_vibe else "sprite",
                translate_required=bool(context.use_llm_translation and "translate" not in removed),
                locale=context.locale,
            )
            if isinstance(custom_hint, str) and custom_hint.strip():
                return TextSection("head", text=custom_hint.rstrip() + "\n"), *self.children

        if format_id == XML_DIALOG_FORMAT_ID:
            if context.uses_vibe:
                head = "xml_vibe_head_top"
            elif context.uses_full_sprite_ids:
                head = "xml_full_sprite_head_top"
            else:
                head = "xml_head_top"
            generated = (
                TextSection("head", text=translate(head)),
                TextSection(
                    "effect",
                    enabled=context.use_effect and "effect" not in removed,
                    text=lambda ctx: ctx.translate("xml_line_effect") + "\n",
                ),
                TextSection(
                    "translation",
                    enabled=context.use_llm_translation and "translate" not in removed,
                    text=lambda ctx: ctx.translate(
                        "xml_line_trans",
                        target_voice_name=ctx.target_voice_name,
                    )
                    + "\n",
                ),
                TextSection(
                    "stage_effects",
                    text=lambda ctx: ctx.translate("xml_stage_effects") + "\n",
                ),
                TextSection("foot", text=translate("xml_foot") + "\n"),
            )
            return *generated, *self.children

        if context.uses_vibe:
            head = "json_vibe_head_top"
        elif context.uses_full_sprite_ids:
            head = "json_full_sprite_head_top"
        else:
            head = "json_head_top"
        generated = (
            TextSection(
                "head",
                text=translate(head),
            ),
            TextSection(
                "speech",
                text=translate(
                    "json_speech_line",
                    example=_json_string_content(translate("json_speech_example")),
                ),
            ),
            TextSection(
                "effect",
                enabled=context.use_effect and "effect" not in removed,
                text=lambda ctx: ctx.translate("json_line_effect"),
            ),
            TextSection(
                "translation",
                enabled=context.use_llm_translation and "translate" not in removed,
                text=lambda ctx: ctx.translate(
                    "json_line_trans",
                    target_voice_name=_json_string_content(ctx.target_voice_name),
                ),
            ),
            TextSection("foot", text=translate("json_foot")),
        )
        return *generated, *self.children
