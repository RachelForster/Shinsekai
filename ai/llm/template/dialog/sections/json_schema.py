"""JSON example and patch-compatible field contract."""

import json
from dataclasses import dataclass

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from ..contracts.fields import build_field_contract_section


def _json_string_content(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


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
            build_field_contract_section(context),
        )
        return *generated, *self.children
