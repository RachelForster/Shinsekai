"""Illustrative JSON output; field rules live in RequirementsSection."""

import json
from dataclasses import dataclass

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
        generated = (
            TextSection(
                "head",
                text=translate(
                    "json_vibe_head_top" if context.uses_vibe else "json_head_top"
                ),
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
