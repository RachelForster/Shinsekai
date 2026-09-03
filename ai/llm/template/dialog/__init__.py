"""Default dialog system prompt, its context and patch-compatible sections."""

from .background_section import BackgroundSection
from .character_section import CharacterSection
from .context import DialogTemplateContext
from .dialog_template_section import DialogTemplateSection
from .json_schema_section import JsonSchemaSection
from .requirements_section import RequirementsSection


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
