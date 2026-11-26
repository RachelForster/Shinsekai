"""Pure localized prompt sections for background setting knowledge extraction."""

from __future__ import annotations

from dataclasses import dataclass

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)


@dataclass(frozen=True)
class KnowledgeExtractionContext(TemplateContext):
    source_text: str = ""


def build_knowledge_extraction_system_section() -> Section[TemplateContext]:
    return Section(
        id="extraction.knowledge.system",
        children=(
            I18nSection(
                id="role",
                key="extraction.knowledge_system",
            ),
        ),
    )


def build_knowledge_extraction_user_section() -> Section[KnowledgeExtractionContext]:
    return Section(
        id="extraction.knowledge.user",
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
                        key="extraction.knowledge_instructions",
                    ),
                    I18nSection(
                        id="schema",
                        priority=20,
                        key="extraction.knowledge_schema",
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
                        key="extraction.knowledge_source_heading",
                    ),
                    TextSection(
                        id="source",
                        priority=20,
                        text=lambda ctx: (ctx.source_text or "").strip(),
                    ),
                ),
            ),
        ),
    )


KNOWLEDGE_EXTRACTION_SPEC = PromptSpec(
    id="extraction.knowledge",
    system_builder=build_knowledge_extraction_system_section,
    user_builder=build_knowledge_extraction_user_section,
)

__all__ = [
    "KNOWLEDGE_EXTRACTION_SPEC",
    "KnowledgeExtractionContext",
    "build_knowledge_extraction_system_section",
    "build_knowledge_extraction_user_section",
]
