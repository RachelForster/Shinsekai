"""Pure Composite prompt sections for fallback image description."""

from __future__ import annotations

from dataclasses import dataclass

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section


@dataclass(frozen=True)
class VisionDescribePromptContext(TemplateContext):
    """Context for fallback image description sent to a VLM."""


def build_vision_describe_section() -> Section[VisionDescribePromptContext]:
    return I18nSection(
        "vision_describe",
        key="generation.vision_describe_prompt",
    )


VISION_DESCRIBE_SPEC: PromptSpec[
    VisionDescribePromptContext, VisionDescribePromptContext
] = PromptSpec(
    id="generation.vision_describe",
    language_policy=PromptLanguagePolicy.FOLLOW_UI,
    user_builder=build_vision_describe_section,
)


def render_vision_describe_prompt(*, locale: str | None = None) -> str:
    ctx = VisionDescribePromptContext(
        locale=normalize_lang(locale) if locale else "zh_CN",
    )
    return VISION_DESCRIBE_SPEC.render_user(ctx)


__all__ = [
    "VISION_DESCRIBE_SPEC",
    "VisionDescribePromptContext",
    "build_vision_describe_section",
    "render_vision_describe_prompt",
]
