"""Requirement leaves and their dialog-level Composite section."""

from dataclasses import dataclass, field, replace
from typing import Any

from sdk.types import RequirementSpec

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from ..contracts.arguments import requirement_arguments
from ..contracts.requirements import resolve_requirement_specs


@dataclass(frozen=True)
class _RequirementRuleSection(Section[DialogTemplateContext]):
    """Private leaf for one localized or patch-resolved rule."""

    arguments: dict[str, Any] = field(default_factory=dict)
    resolved_text: str | None = None

    def requirement_text(self, context: DialogTemplateContext) -> str:
        if self.resolved_text is not None:
            return self.resolved_text
        return context.translate(self.id, **self.arguments)

    def _render_self(self, context: DialogTemplateContext) -> str:
        return f"- {self.requirement_text(context)}\n"


def build_requirement_sections(
    context: DialogTemplateContext,
) -> tuple[_RequirementRuleSection, ...]:
    arguments = requirement_arguments(context)
    definitions = (
        ("r_cot", 5, context.use_cot),
        ("r_format", 10, True),
        ("r_user_display_name_tool", 15, True),
        ("r_cname", 20, True),
        ("r_sprite", 30, True),
        ("r_non_sprite", 40, True),
        ("r_scene", 50, context.has_real_background),
        ("r_bgm", 60, context.has_real_background),
        ("r_speech", 70, True),
        ("r_array", 80, True),
        ("r_speech_max_chars", 90, context.max_speech_chars > 0),
        ("r_dialog_max_items", 95, context.max_dialog_items > 0),
        ("r_narration", 100, context.use_narration),
        ("r_choice_pos", 110, context.use_choice),
        ("r_choice_format", 120, context.use_choice),
        ("r_choice_balance", 130, context.use_choice),
        ("r_stats", 140, context.use_stat),
        ("r_cg", 150, context.use_cg),
        ("r_translate", 160, context.use_llm_translation),
        ("r_effect", 170, context.use_effect),
    )
    return tuple(
        _RequirementRuleSection(
            id=rule_id,
            priority=priority,
            enabled=enabled,
            arguments=arguments.get(rule_id, {}),
        )
        for rule_id, priority, enabled in definitions
    )


def _resolve_requirement_sections(
    sections: tuple[_RequirementRuleSection, ...],
    context: DialogTemplateContext,
) -> tuple[_RequirementRuleSection, ...]:
    specs = resolve_requirement_specs(sections, context)
    resolved = tuple(
        _RequirementRuleSection(
            id=spec.id,
            priority=spec.order,
            enabled=spec.enabled,
            resolved_text=spec.text,
        )
        for spec in specs
    )
    resolved_ids = {section.id for section in resolved}
    disabled = tuple(
        replace(section, enabled=False)
        for section in sections
        if section.id not in resolved_ids
    )
    return *resolved, *disabled


def build_requirements(context: DialogTemplateContext) -> list[RequirementSpec]:
    return resolve_requirement_specs(build_requirement_sections(context), context)


@dataclass(frozen=True)
class RequirementsSection(Section[DialogTemplateContext]):
    id: str = "requirements"

    def _resolve_children(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
        rules = TextSection(
            "rules",
            priority=20,
            text=context.translate("requirements_header"),
            children=_resolve_requirement_sections(
                build_requirement_sections(context), context
            ),
        )
        extra_bgm = TextSection(
            "extra_bgm",
            enabled=context.has_real_background,
            text=lambda ctx: ctx.translate("closing_extra_bgm"),
        )
        generated = (
            TextSection("tools", text=lambda ctx: ctx.tools_block, priority=10),
            rules,
            TextSection(
                "closing",
                priority=30,
                text=lambda ctx: ctx.translate("closing", extra=extra_bgm.render(ctx)),
            ),
            TextSection(
                "json_reminder",
                priority=40,
                text=lambda ctx: f"{ctx.json_reminder}\n",
            ),
        )
        return *generated, *self.children
