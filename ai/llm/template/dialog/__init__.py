"""Default dialog system prompt, its context and patch-compatible sections."""

from ai.llm.template.dialog.context import (
    DialogTemplateContext,
    EffectCatalogContext,
    EffectCatalogEntry,
)
from ai.llm.template.dialog.sections.effects import EffectCatalogSection
from .sections.background import BackgroundSection
from .sections.character import CharacterSection
from .sections.dialog_template import DialogTemplateSection
from .sections.json_schema import JsonSchemaSection
from .sections.requirements import RequirementsSection


def build_dialog_section() -> DialogTemplateSection:
    """Compatibility factory for callers using the original builder API."""
    return DialogTemplateSection()


__all__ = [
    "BackgroundSection",
    "CharacterSection",
    "DialogTemplateContext",
    "DialogTemplateSection",
    "EffectCatalogContext",
    "EffectCatalogEntry",
    "EffectCatalogSection",
    "JsonSchemaSection",
    "RequirementsSection",
    "build_dialog_section",
]
