"""The dialog prompt root and its four major sections."""

from dataclasses import dataclass, field

from ..core import Section
from .background_section import BackgroundSection
from .character_section import CharacterSection
from .context import DialogTemplateContext
from .json_schema_section import JsonSchemaSection
from .requirements_section import RequirementsSection


@dataclass(frozen=True)
class DialogTemplateSection(Section[DialogTemplateContext]):
    id: str = "dialog.system"
    children: tuple[Section[DialogTemplateContext], ...] = field(
        default_factory=lambda: (
            JsonSchemaSection(priority=10),
            CharacterSection(priority=20),
            BackgroundSection(priority=30),
            RequirementsSection(priority=40),
        )
    )

    def render_content(self, context: DialogTemplateContext) -> str:
        return context.translate("preamble", names=context.names)
