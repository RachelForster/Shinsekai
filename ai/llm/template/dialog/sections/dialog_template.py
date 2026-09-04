"""Root of the default dialog prompt."""

from dataclasses import dataclass, field

from ...core import Section
from ..context import DialogTemplateContext
from .background import BackgroundSection
from .character import CharacterSection
from .json_schema import JsonSchemaSection
from .requirements import RequirementsSection


@dataclass(frozen=True)
class DialogTemplateSection(Section[DialogTemplateContext]):
    """Render the preamble and four directly owned domain sections."""

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
