"""Declarative requirement nodes with feature selection carried by enabled."""

from sdk.types import RequirementSpec

from ..core import Section, TextSection
from .context import DialogTemplateContext
from .requirement_arguments import requirement_arguments
from .requirement_section import RequirementSection, resolve_requirement_specs


def build_requirement_sections(
    context: DialogTemplateContext,
) -> tuple[RequirementSection, ...]:
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
        RequirementSection(
            id=rule_id,
            priority=priority,
            enabled=enabled,
            arguments=arguments.get(rule_id, {}),
        )
        for rule_id, priority, enabled in definitions
    )


def build_requirements(context: DialogTemplateContext) -> list[RequirementSpec]:
    return resolve_requirement_specs(build_requirement_sections(context), context)


class RequirementsSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        tree = TextSection(
            self.id,
            text=context.translate("requirements_header"),
            children=tuple(
                TextSection(
                    item.id,
                    priority=item.order,
                    enabled=item.enabled,
                    text=f"- {item.text}\n",
                )
                for item in build_requirements(context)
            ),
        )
        return tree.render(context)
