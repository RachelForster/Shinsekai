"""Default dialog system prompt, its context and patch-compatible sections."""

from .context import DialogTemplateContext
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
    "JsonSchemaSection",
    "RequirementsSection",
    "build_dialog_section",
]
