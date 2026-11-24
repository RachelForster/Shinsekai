"""Pure localized prompt sections for plain and dual-granularity memory extraction."""

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
class MemorySimpleExtractionContext(TemplateContext):
    dialogue: str = ""
    default_character_name: str = "user"


@dataclass(frozen=True)
class MemoryStructuredExtractionContext(TemplateContext):
    dialogue: str = ""
    character_names: tuple[str, ...] = ()
    now_iso: str = ""


def build_memory_extraction_system_section() -> Section[TemplateContext]:
    return Section(
        id="extraction.memory.system",
        children=(
            I18nSection(
                id="role",
                key="extraction.memory_system",
            ),
        ),
    )


def build_memory_extraction_user_section() -> Section[MemorySimpleExtractionContext]:
    return Section(
        id="extraction.memory.simple.user",
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
                        key="extraction.memory_simple_instructions",
                        params=lambda ctx: {
                            "default_character": repr(
                                (ctx.default_character_name or "").strip() or "user"
                            ),
                        },
                    ),
                    I18nSection(
                        id="schema",
                        priority=20,
                        key="extraction.memory_simple_schema",
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
                        key="extraction.memory_dialogue_heading",
                    ),
                    TextSection(
                        id="dialogue",
                        priority=20,
                        text=lambda ctx: (ctx.dialogue or "").strip(),
                    ),
                ),
            ),
        ),
    )


def _structured_header_params(
    context: MemoryStructuredExtractionContext,
) -> dict[str, str]:
    cleaned_chars = [
        str(c or "").strip() for c in context.character_names if str(c or "").strip()
    ]
    default_char = cleaned_chars[0] if cleaned_chars else "user"
    chars_desc = (
        ", ".join(repr(c) for c in cleaned_chars) if cleaned_chars else repr("user")
    )
    return {
        "anchor": (context.now_iso or "").strip(),
        "chars_desc": chars_desc,
        "default_char": repr(default_char),
    }


def build_structured_memory_extraction_user_section() -> Section[
    MemoryStructuredExtractionContext
]:
    return Section(
        id="extraction.memory.structured.user",
        separator="\n\n",
        children=(
            Section(
                id="directive",
                priority=10,
                separator="\n",
                children=(
                    I18nSection(
                        id="header",
                        priority=10,
                        key="extraction.memory_structured_header",
                        params=_structured_header_params,
                    ),
                    I18nSection(
                        id="rules",
                        priority=20,
                        key="extraction.memory_structured_rules",
                    ),
                    I18nSection(
                        id="schema",
                        priority=30,
                        key="extraction.memory_structured_schema",
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
                        key="extraction.memory_dialogue_heading",
                    ),
                    TextSection(
                        id="dialogue",
                        priority=20,
                        text=lambda ctx: (ctx.dialogue or "").strip(),
                    ),
                ),
            ),
        ),
    )


MEMORY_SIMPLE_EXTRACTION_SPEC = PromptSpec(
    id="extraction.memory.simple",
    system_builder=build_memory_extraction_system_section,
    user_builder=build_memory_extraction_user_section,
)

MEMORY_STRUCTURED_EXTRACTION_SPEC = PromptSpec(
    id="extraction.memory.structured",
    system_builder=build_memory_extraction_system_section,
    user_builder=build_structured_memory_extraction_user_section,
)

__all__ = [
    "MEMORY_SIMPLE_EXTRACTION_SPEC",
    "MEMORY_STRUCTURED_EXTRACTION_SPEC",
    "MemorySimpleExtractionContext",
    "MemoryStructuredExtractionContext",
    "build_memory_extraction_system_section",
    "build_memory_extraction_user_section",
    "build_structured_memory_extraction_user_section",
]
