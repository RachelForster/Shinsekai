"""Adapter mapping DialogTemplateContext onto SDK dialog-format hook DTOs."""

from __future__ import annotations

from sdk.adapters.dialog_format import DialogFormatPromptContext

from .context import DialogTemplateContext
from .sections.field_requirements import removed_optional_fields


def build_dialog_format_prompt_context(
    context: DialogTemplateContext,
) -> DialogFormatPromptContext:
    """Build an SDK-level switch snapshot without exposing template internals."""
    removed = tuple(sorted(removed_optional_fields(context)))
    return DialogFormatPromptContext(
        locale=str(context.locale or "zh_CN"),
        media_field="vibe" if context.uses_vibe else "sprite",
        uses_vibe=bool(context.uses_vibe),
        uses_full_sprite_ids=bool(context.uses_full_sprite_ids),
        has_real_background=bool(context.has_real_background),
        use_cot=bool(context.use_cot),
        use_narration=bool(context.use_narration),
        use_choice=bool(context.use_choice),
        use_stat=bool(context.use_stat),
        use_cg=bool(context.use_cg),
        use_effect=bool(context.use_effect),
        use_llm_translation=bool(context.use_llm_translation),
        target_voice_name=str(context.target_voice_name or ""),
        names=str(context.names or ""),
        max_speech_chars=int(context.max_speech_chars or 0),
        max_dialog_items=int(context.max_dialog_items or 0),
        removed_optional_fields=removed,
    )
