"""Pure localized prompt section for malformed runtime dialogue JSON repair."""

from __future__ import annotations

from dataclasses import dataclass

from ai.llm.template.core import I18nSection, PromptSpec, Section, TemplateContext


@dataclass(frozen=True)
class DialogRepairPromptContext(TemplateContext):
    media_field: str = "sprite"
    retry: bool = False


class _DialogRepairInstructionSection(Section[DialogRepairPromptContext]):
    def _resolve_children(
        self,
        context: DialogRepairPromptContext,
    ) -> tuple[Section[DialogRepairPromptContext], ...]:
        key = (
            "session.dialog_repair_retry"
            if context.retry
            else "session.dialog_repair_initial"
        )
        return (
            I18nSection(
                id="instruction",
                key=key,
                params=lambda ctx: {"media_field": ctx.media_field},
            ),
        )


def build_dialog_repair_user_section() -> Section[DialogRepairPromptContext]:
    return _DialogRepairInstructionSection(id="session.dialog_repair.user")


DIALOG_REPAIR_PROMPT_SPEC = PromptSpec(
    id="session.dialog_repair",
    user_builder=build_dialog_repair_user_section,
)

__all__ = [
    "DIALOG_REPAIR_PROMPT_SPEC",
    "DialogRepairPromptContext",
    "build_dialog_repair_user_section",
]
