"""Illustrative output schema; field rules live in RequirementsSection."""

import json
from dataclasses import dataclass

from core.messaging.formats.registry import resolve_dialog_format
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from ..format_context import build_dialog_format_prompt_context
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
            prompt_ctx = build_dialog_format_prompt_context(context)
            translate_required = bool(
                context.use_llm_translation and "translate" not in removed
            )
            try:
                custom_hint = fmt.render_schema_hint(
                    media_field=prompt_ctx.media_field,
                    translate_required=translate_required,
                    locale=context.locale,
                    prompt_context=prompt_ctx,
                )
            except TypeError:
                custom_hint = fmt.render_schema_hint(
                    media_field=prompt_ctx.media_field,
                    translate_required=translate_required,
                    locale=context.locale,
                )
            if isinstance(custom_hint, str) and custom_hint.strip():
                return TextSection("head", text=custom_hint.rstrip() + "\n"), *self.children

        if format_id == XML_DIALOG_FORMAT_ID:
            if context.uses_vibe:
                variant = "vibe"
            elif context.uses_full_sprite_ids:
                variant = "full"
            else:
                variant = "indexed"
            effect_enabled = bool(context.use_effect and "effect" not in removed)
            trans_enabled = bool(context.use_llm_translation and "translate" not in removed)
            generated = (
                TextSection("head_intro", text=lambda ctx: ctx.translate("xml_schema_intro") + "\n"),
                TextSection(
                    "example_cot",
                    enabled=context.use_cot,
                    text=lambda ctx: ctx.translate("xml_example_cot") + "\n",
                ),
                TextSection(
                    "example_scene",
                    enabled=context.has_real_background,
                    text=lambda ctx, v=variant: ctx.translate(f"xml_example_scene_{v}") + "\n",
                ),
                TextSection(
                    "example_bgm",
                    enabled=context.has_real_background,
                    text=lambda ctx, v=variant: ctx.translate(f"xml_example_bgm_{v}") + "\n",
                ),
                TextSection(
                    "example_say",
                    text=lambda ctx, v=variant, eff=effect_enabled, tr=trans_enabled: ctx.translate(
                        f"xml_example_say_{v}",
                        effect_attr=ctx.translate("xml_example_effect_attr") if eff else "",
                        trans_tag=(
                            ctx.translate("xml_example_trans_tag", target_voice_name=ctx.target_voice_name)
                            if tr
                            else ""
                        ),
                    )
                    + "\n",
                ),
                TextSection(
                    "example_narr",
                    enabled=context.use_narration,
                    text=lambda ctx: ctx.translate("xml_example_narr") + "\n",
                ),
                TextSection(
                    "example_stat",
                    enabled=context.use_stat,
                    text=lambda ctx: ctx.translate("xml_example_stat") + "\n",
                ),
                TextSection(
                    "example_cg",
                    enabled=context.use_cg,
                    text=lambda ctx: ctx.translate("xml_example_cg") + "\n",
                ),
                TextSection(
                    "example_choice",
                    enabled=context.use_choice,
                    text=lambda ctx: ctx.translate("xml_example_choice") + "\n",
                ),
                TextSection(
                    "effect",
                    enabled=effect_enabled,
                    text=lambda ctx: ctx.translate("xml_line_effect") + "\n",
                ),
                TextSection(
                    "translation",
                    enabled=trans_enabled,
                    text=lambda ctx: ctx.translate(
                        "xml_line_trans",
                        target_voice_name=ctx.target_voice_name,
                    )
                    + "\n",
                ),
                TextSection(
                    "stage_effects",
                    text=lambda ctx: ctx.translate(
                        "xml_stage_effects"
                        if ctx.has_real_background
                        else "xml_stage_effects_motion_only"
                    )
                    + "\n",
                ),
                TextSection("foot", text=lambda ctx: ctx.translate("xml_foot") + "\n"),
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
