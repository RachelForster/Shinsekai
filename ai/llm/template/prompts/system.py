"""Runtime system prompt composition."""

from dataclasses import dataclass

from ai.llm.template.core.context import TemplateContext
from ai.llm.template.core.section import Section, TextSection
from ai.llm.template.dialog.context import EffectCatalogContext
from ai.llm.template.dialog.sections.effects import EffectCatalogSection


@dataclass(frozen=True)
class RuntimePromptContext(TemplateContext):
    system_template: str
    user_scenario: str
    json_reminder: str
    effect_catalog: EffectCatalogContext | None = None


def build_runtime_prompt_section() -> Section[RuntimePromptContext]:
    """Compose prepared system rules, scenario and the final output reminder."""
    return Section(
        "runtime.system",
        separator="\n",
        children=(
            TextSection(
                "system", priority=10, text=lambda context: context.system_template
            ),
            EffectCatalogSection(priority=15),
            TextSection(
                "scenario", priority=20, text=lambda context: context.user_scenario
            ),
            TextSection(
                "json_reminder", priority=30, text=lambda context: context.json_reminder
            ),
        ),
    )
