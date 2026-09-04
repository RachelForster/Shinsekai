"""Runtime system prompt composition."""

from dataclasses import dataclass

from ..core import Section, TemplateContext, TextSection


@dataclass(frozen=True)
class RuntimePromptContext(TemplateContext):
    system_template: str
    user_scenario: str
    json_reminder: str


def build_runtime_prompt_section() -> Section[RuntimePromptContext]:
    """Compose prepared system rules, scenario and the final output reminder."""
    return Section(
        "runtime.system",
        separator="\n",
        children=(
            TextSection(
                "system", priority=10, text=lambda context: context.system_template
            ),
            TextSection(
                "scenario", priority=20, text=lambda context: context.user_scenario
            ),
            TextSection(
                "json_reminder", priority=30, text=lambda context: context.json_reminder
            ),
        ),
    )
