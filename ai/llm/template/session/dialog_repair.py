"""Pure localized prompt section for malformed runtime dialogue JSON repair."""

from __future__ import annotations

from dataclasses import dataclass

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)


@dataclass(frozen=True)
class DialogRepairPromptContext(TemplateContext):
    media_field: str = "sprite"
    retry: bool = False
    allow_unbound_speakers: bool = False
    bound_speakers: tuple[str, ...] = ()


class _DialogRepairInstructionSection(Section[DialogRepairPromptContext]):
    def _resolve_children(
        self,
        context: DialogRepairPromptContext,
    ) -> tuple[Section[DialogRepairPromptContext], ...]:
        if context.allow_unbound_speakers:
            key = (
                "session.dialog_repair_retry_selective"
                if context.retry
                else "session.dialog_repair_initial_selective"
            )
        else:
            key = (
                "session.dialog_repair_retry"
                if context.retry
                else "session.dialog_repair_initial"
            )
        children: list[Section[DialogRepairPromptContext]] = [
            I18nSection(
                id="instruction",
                priority=10,
                key=key,
                params=lambda ctx: {"media_field": ctx.media_field},
            ),
        ]
        speakers = tuple(
            cleaned
            for raw in context.bound_speakers
            if (cleaned := str(raw or "").strip())
        )
        if context.allow_unbound_speakers and speakers:
            children.append(
                Section(
                    id="bound_speakers",
                    priority=20,
                    separator="\n",
                    children=(
                        I18nSection(
                            id="heading",
                            priority=10,
                            key="session.dialog_repair_bound_speakers_heading",
                            params=lambda ctx: {"media_field": ctx.media_field},
                        ),
                        TextSection(
                            id="names",
                            priority=20,
                            text=", ".join(speakers),
                        ),
                    ),
                )
            )
        return tuple(children)


def build_dialog_repair_user_section() -> Section[DialogRepairPromptContext]:
    return _DialogRepairInstructionSection(
        id="session.dialog_repair.user",
        separator="\n\n",
    )


DIALOG_REPAIR_PROMPT_SPEC = PromptSpec(
    id="session.dialog_repair",
    user_builder=build_dialog_repair_user_section,
)

__all__ = [
    "DIALOG_REPAIR_PROMPT_SPEC",
    "DialogRepairPromptContext",
    "build_dialog_repair_user_section",
]
