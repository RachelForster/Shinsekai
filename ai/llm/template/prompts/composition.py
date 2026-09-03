"""System and user prompt composition using the same Section primitives."""

from dataclasses import dataclass

from ..core import Section, TemplateContext, TextSection


@dataclass(frozen=True)
class RuntimePromptContext(TemplateContext):
    system_template: str
    user_scenario: str
    json_reminder: str


@dataclass(frozen=True)
class UserPromptContext(TemplateContext):
    user_input: str
    prefix: str = ""
    suffix: str = ""


def build_runtime_prompt_section() -> Section[RuntimePromptContext]:
    """Compose prepared system rules, scenario and the final output reminder.

    Scenario defaults and the trailing newline remain the caller's policy.
    """
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


def build_user_prompt_section(separator: str = "\n\n") -> Section[UserPromptContext]:
    """Surround literal user input with optional context, without interpolation."""
    return Section(
        "user",
        separator=separator,
        children=(
            TextSection("prefix", priority=10, text=lambda context: context.prefix),
            TextSection("input", priority=20, text=lambda context: context.user_input),
            TextSection("suffix", priority=30, text=lambda context: context.suffix),
        ),
    )
