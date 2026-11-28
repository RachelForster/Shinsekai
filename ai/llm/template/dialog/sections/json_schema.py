"""Illustrative output schema; field rules live in RequirementsSection."""

from dataclasses import dataclass

from ai.llm.formats import resolve_dialog_format
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, DialogFormatPromptContext

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from ..format_context import build_dialog_format_prompt_context
from .field_requirements import removed_optional_fields


def _render_schema_hint_for_format(
    fmt,
    *,
    prompt_ctx: DialogFormatPromptContext,
    translate_required: bool,
    locale: str,
) -> str | None:
    try:
        return fmt.render_schema_hint(
            media_field=prompt_ctx.media_field,
            translate_required=translate_required,
            locale=locale,
            prompt_context=prompt_ctx,
        )
    except TypeError:
        return fmt.render_schema_hint(
            media_field=prompt_ctx.media_field,
            translate_required=translate_required,
            locale=locale,
        )


@dataclass(frozen=True)
class JsonSchemaSection(Section[DialogTemplateContext]):
    id: str = "json_schema"

    def _resolve_children(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
        removed = removed_optional_fields(context)
        format_id = str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
        fmt = resolve_dialog_format(format_id)
        prompt_ctx = build_dialog_format_prompt_context(context)
        translate_required = bool(
            context.use_llm_translation and "translate" not in removed
        )
        hint = _render_schema_hint_for_format(
            fmt,
            prompt_ctx=prompt_ctx,
            translate_required=translate_required,
            locale=context.locale,
        )
        if (not isinstance(hint, str) or not hint.strip()) and fmt.format_id != DEFAULT_DIALOG_FORMAT_ID:
            hint = _render_schema_hint_for_format(
                resolve_dialog_format(DEFAULT_DIALOG_FORMAT_ID),
                prompt_ctx=prompt_ctx,
                translate_required=translate_required,
                locale=context.locale,
            )
        if not isinstance(hint, str) or not hint.strip():
            return tuple(self.children)
        rendered = hint if hint.endswith("\n") else f"{hint.rstrip(chr(13) + chr(10))}\n"
        return TextSection("head", text=rendered), *self.children
