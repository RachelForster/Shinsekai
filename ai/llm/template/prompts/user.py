"""Literal user prompt composition."""

from dataclasses import dataclass

from ..core import Section, TemplateContext, TextSection


@dataclass(frozen=True)
class UserPromptContext(TemplateContext):
    user_input: str
    prefix: str = ""
    suffix: str = ""


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
