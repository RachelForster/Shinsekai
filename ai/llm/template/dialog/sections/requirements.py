"""Requirement leaves and their dialog-level Composite section."""

from dataclasses import dataclass, field, replace
from typing import Any

from ai.llm.formats import resolve_dialog_format
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID
from sdk.types import RequirementSpec

from ...core import Section, TextSection
from ..context import DialogTemplateContext
from ..format_context import build_dialog_format_prompt_context
from ..patches import apply_requirement_patches
from .field_requirements import build_field_requirements, removed_optional_fields


@dataclass(frozen=True)
class _RequirementRuleSection(Section[DialogTemplateContext]):
    """Private leaf for one localized or patch-resolved rule."""

    arguments: dict[str, Any] = field(default_factory=dict)
    resolved_text: str | None = None
    translation_key: str | None = None

    def requirement_text(self, context: DialogTemplateContext) -> str:
        if self.resolved_text is not None:
            return self.resolved_text
        return context.translate(self.translation_key or self.id, **self.arguments)

    def _render_self(self, context: DialogTemplateContext) -> str:
        return f"- {self.requirement_text(context)}\n"


def _fallback_requirement_sections(
    context: DialogTemplateContext,
) -> tuple[_RequirementRuleSection, ...]:
    definitions: tuple[tuple[str, int, bool, str | None, dict[str, Any]], ...] = (
        ("r_format", 10, True, "custom_r_format", {}),
        ("r_user_display_name_tool", 15, True, None, {}),
        (
            "r_sprite",
            30,
            not context.uses_vibe,
            "r_full_sprite" if context.uses_full_sprite_ids else None,
            {},
        ),
        ("r_vibe", 30, context.uses_vibe, None, {}),
        (
            "r_speech",
            70,
            True,
            None,
            {"speech_lang_name": context.translate("speech_lang_name")},
        ),
        (
            "r_speech_max_chars",
            90,
            context.max_speech_chars > 0,
            "custom_r_speech_max_chars",
            {"n": context.max_speech_chars},
        ),
        (
            "r_dialog_max_items",
            95,
            context.max_dialog_items > 0,
            "custom_r_dialog_max_items",
            {"n": context.max_dialog_items},
        ),
        ("r_choice_balance", 130, context.use_choice, None, {}),
    )
    return tuple(
        _RequirementRuleSection(
            id=rule_id,
            priority=priority,
            enabled=enabled,
            arguments=args,
            translation_key=translation_key,
        )
        for rule_id, priority, enabled, translation_key, args in definitions
    )


def build_requirement_sections(
    context: DialogTemplateContext,
) -> tuple[_RequirementRuleSection, ...]:
    format_id = str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
    fmt = resolve_dialog_format(format_id)
    format_specs = fmt.render_requirements(build_dialog_format_prompt_context(context))
    if format_specs:
        sections = [
            _RequirementRuleSection(
                id=spec.id,
                priority=spec.order,
                enabled=spec.enabled,
                resolved_text=spec.text,
            )
            for spec in format_specs
        ]
        if not any(spec.id == "r_user_display_name_tool" for spec in format_specs):
            sections.append(
                _RequirementRuleSection(
                    id="r_user_display_name_tool",
                    priority=15,
                    enabled=True,
                )
            )
        sections.sort(key=lambda section: section.priority)
        return tuple(sections)
    return _fallback_requirement_sections(context)


def _resolve_requirement_specs(
    sections: tuple[_RequirementRuleSection, ...],
    context: DialogTemplateContext,
) -> list[RequirementSpec]:
    removed_rules = {f"r_{key}" for key in removed_optional_fields(context)}
    specs = [
        RequirementSpec(section.id, section.requirement_text(context), section.priority)
        for section in sections
        if section.enabled and section.id not in removed_rules
    ]
    return [
        spec
        for spec in apply_requirement_patches(specs, context.output_contract_patches)
        if spec.id not in removed_rules
    ]


def _resolve_requirement_sections(
    sections: tuple[_RequirementRuleSection, ...],
    context: DialogTemplateContext,
) -> tuple[_RequirementRuleSection, ...]:
    specs = _resolve_requirement_specs(sections, context)
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
    return _resolve_requirement_specs(build_requirement_sections(context), context)


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
            children=(
                *_resolve_requirement_sections(
                    build_requirement_sections(context), context
                ),
                build_field_requirements(context),
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
