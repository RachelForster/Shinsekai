"""Pure localized prompt builders for novel character & alias extraction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)
from sdk.lang import normalize_lang


@dataclass(frozen=True)
class NovelCastExtractionContext(TemplateContext):
    excerpts: tuple[str, ...] = ()


def _format_excerpts(context: NovelCastExtractionContext) -> str:
    cleaned = [
        text
        for raw in context.excerpts
        if (text := str(raw or "").strip())
    ]
    return "\n\n---\n\n".join(cleaned)


def build_novel_cast_system_section() -> Section[TemplateContext]:
    return Section(
        id="extraction.novel_cast.system",
        children=(
            I18nSection(
                id="role",
                key="extraction.novel_cast_system",
            ),
        ),
    )


def build_novel_cast_user_section() -> Section[NovelCastExtractionContext]:
    return Section(
        id="extraction.novel_cast.user",
        separator="\n\n",
        children=(
            Section(
                id="directive",
                priority=10,
                separator="\n",
                children=(
                    I18nSection(
                        id="instructions",
                        priority=10,
                        key="extraction.novel_cast_instructions",
                    ),
                    I18nSection(
                        id="schema",
                        priority=20,
                        key="extraction.novel_cast_schema",
                    ),
                ),
            ),
            Section(
                id="payload",
                priority=20,
                separator="\n",
                children=(
                    I18nSection(
                        id="heading",
                        priority=10,
                        key="extraction.novel_cast_excerpt_heading",
                    ),
                    TextSection(
                        id="excerpts",
                        priority=20,
                        text=_format_excerpts,
                    ),
                ),
            ),
        ),
    )


NOVEL_CAST_EXTRACTION_SPEC = PromptSpec(
    id="extraction.novel_cast",
    system_builder=build_novel_cast_system_section,
    user_builder=build_novel_cast_user_section,
)


def render_novel_cast_prompts(
    excerpts: Sequence[str],
    *,
    locale: str | None = None,
) -> tuple[str, str]:
    """Render localized system & user prompts for extracting novel cast members."""
    context = NovelCastExtractionContext(
        locale=normalize_lang(locale),
        excerpts=tuple(str(item or "") for item in excerpts),
    )
    return (
        NOVEL_CAST_EXTRACTION_SPEC.render_system(context),
        NOVEL_CAST_EXTRACTION_SPEC.render_user(context),
    )


__all__ = [
    "NOVEL_CAST_EXTRACTION_SPEC",
    "NovelCastExtractionContext",
    "build_novel_cast_system_section",
    "build_novel_cast_user_section",
    "render_novel_cast_prompts",
]
