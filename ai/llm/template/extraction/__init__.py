"""Pure localized prompt sections for memory and knowledge extraction."""

from ai.llm.template.extraction.knowledge import (
    KNOWLEDGE_EXTRACTION_SPEC,
    KnowledgeExtractionContext,
    build_knowledge_extraction_system_section,
    build_knowledge_extraction_user_section,
)
from ai.llm.template.extraction.memory import (
    MEMORY_SIMPLE_EXTRACTION_SPEC,
    MEMORY_STRUCTURED_EXTRACTION_SPEC,
    MemorySimpleExtractionContext,
    MemoryStructuredExtractionContext,
    build_memory_extraction_system_section,
    build_memory_extraction_user_section,
    build_structured_memory_extraction_user_section,
)

__all__ = [
    "KNOWLEDGE_EXTRACTION_SPEC",
    "KnowledgeExtractionContext",
    "MEMORY_SIMPLE_EXTRACTION_SPEC",
    "MEMORY_STRUCTURED_EXTRACTION_SPEC",
    "MemorySimpleExtractionContext",
    "MemoryStructuredExtractionContext",
    "build_knowledge_extraction_system_section",
    "build_knowledge_extraction_user_section",
    "build_memory_extraction_system_section",
    "build_memory_extraction_user_section",
    "build_structured_memory_extraction_user_section",
]
