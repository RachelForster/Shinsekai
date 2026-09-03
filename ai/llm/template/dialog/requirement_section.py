"""Localized rule leaf and the bridge to the existing SDK patch protocol."""

from dataclasses import dataclass, field
from typing import Any, Sequence

from sdk.types import RequirementSpec

from ..core import Section
from .context import DialogTemplateContext
from .patches import apply_requirement_patches


@dataclass(frozen=True)
class RequirementSection(Section[DialogTemplateContext]):
    arguments: dict[str, Any] = field(default_factory=dict)

    def render_content(self, context: DialogTemplateContext) -> str:
        return context.translate(self.id, **self.arguments)


def resolve_requirement_specs(
    sections: Sequence[RequirementSection],
    context: DialogTemplateContext,
) -> list[RequirementSpec]:
    # Feature-disabled rules were absent in the old patch input. Preserve that
    # boundary: patching one is a no-op, while add_requirements may introduce it.
    specs = [
        RequirementSpec(section.id, section.render(context), section.priority)
        for section in sections
        if section.enabled
    ]
    return apply_requirement_patches(specs, context.output_contract_patches)
