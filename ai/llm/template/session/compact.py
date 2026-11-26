"""Pure localized prompt sections for conversation context compaction."""

from __future__ import annotations

from dataclasses import dataclass

from ai.llm.template.core import (
    I18nSection,
    PROMPT_CATALOG,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)


@dataclass(frozen=True)
class CompactTranscriptTurn:
    role: str
    content: str
    tool_name: str = ""


@dataclass(frozen=True)
class CompactPromptContext(TemplateContext):
    turns: tuple[CompactTranscriptTurn, ...] = ()
    extra_instructions: tuple[str, ...] = ()


class _ExtraRequirementsSection(Section[CompactPromptContext]):
    def _resolve_children(
        self,
        context: CompactPromptContext,
    ) -> tuple[Section[CompactPromptContext], ...]:
        items = tuple(
            cleaned
            for raw in context.extra_instructions
            if (cleaned := str(raw or "").strip())
        )
        if not items:
            return ()
        return (
            I18nSection(
                id="heading",
                priority=10,
                key="session.compact_extra_requirements_heading",
            ),
            TextSection(
                id="items",
                priority=20,
                text="\n".join(f"- {item}" for item in items),
            ),
        )


def _format_transcript_lines(context: CompactPromptContext) -> str:
    lines: list[str] = []
    for turn in context.turns:
        role = turn.role
        if role == "user":
            label = context.tr("session.compact_role_user")
        elif role == "assistant":
            label = context.tr("session.compact_role_assistant")
        elif role == "tool":
            label = context.tr("session.compact_role_tool", name=turn.tool_name)
        else:
            label = role
        lines.append(f"{label}: {turn.content}")
    return "\n".join(lines)


def build_compact_system_section() -> Section[TemplateContext]:
    return Section(
        id="session.compact.system",
        children=(
            I18nSection(
                id="role",
                key="session.compact_system",
            ),
        ),
    )


def build_compact_user_section() -> Section[CompactPromptContext]:
    return Section(
        id="session.compact.user",
        separator="\n\n",
        children=(
            I18nSection(
                id="intro",
                priority=10,
                key="session.compact_user_intro",
            ),
            Section(
                id="history",
                priority=20,
                separator="\n\n",
                children=(
                    I18nSection(
                        id="heading",
                        priority=10,
                        key="session.compact_history_heading",
                    ),
                    TextSection(
                        id="transcript",
                        priority=20,
                        text=_format_transcript_lines,
                    ),
                ),
            ),
            _ExtraRequirementsSection(
                id="extra_requirements",
                priority=25,
                separator="\n",
            ),
            I18nSection(
                id="outro",
                priority=30,
                key="session.compact_user_outro",
            ),
        ),
    )


COMPACT_PROMPT_SPEC = PromptSpec(
    id="session.compact",
    system_builder=build_compact_system_section,
    user_builder=build_compact_user_section,
)


def render_omitted_history_notice(*, locale: str | None = "zh_CN") -> str:
    return PROMPT_CATALOG.translate("session.compact_omitted_history", locale=locale)


def render_compact_failure_fallback(*, locale: str | None = "zh_CN") -> str:
    return PROMPT_CATALOG.translate("session.compact_failed_fallback", locale=locale)


__all__ = [
    "COMPACT_PROMPT_SPEC",
    "CompactPromptContext",
    "CompactTranscriptTurn",
    "build_compact_system_section",
    "build_compact_user_section",
    "render_compact_failure_fallback",
    "render_omitted_history_notice",
]
