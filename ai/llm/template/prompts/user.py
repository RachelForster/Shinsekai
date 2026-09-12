"""Literal user prompt composition."""

from dataclasses import dataclass
from collections.abc import Mapping
import json

from ..core import Section, TemplateContext, TextSection


@dataclass(frozen=True)
class UserPromptContext(TemplateContext):
    user_input: str
    prefix: str = ""
    suffix: str = ""
    background: Mapping[str, str | int] | None = None
    attachments: tuple[str, ...] = ()


def _background_text(context: UserPromptContext) -> str:
    if not context.background:
        return ""
    return (
        "[当前显示背景]\n"
        + json.dumps(dict(context.background), ensure_ascii=False)
        + "\n[/当前显示背景]"
    )


def build_user_prompt_section(separator: str = "\n\n") -> Section[UserPromptContext]:
    """Surround literal user input with optional context, without interpolation."""
    return Section(
        "user",
        separator=separator,
        children=(
            TextSection("prefix", priority=10, text=lambda context: context.prefix),
            TextSection("background", priority=15, text=_background_text),
            TextSection("input", priority=20, text=lambda context: context.user_input),
            TextSection(
                "attachments", priority=25,
                text=lambda context: "\n\n".join(part for part in context.attachments if part),
            ),
            TextSection("suffix", priority=30, text=lambda context: context.suffix),
        ),
    )
