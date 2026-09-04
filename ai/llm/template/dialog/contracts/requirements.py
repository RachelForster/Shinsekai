"""Bridge requirement sections to the existing SDK patch protocol."""

from collections.abc import Sequence
from typing import Protocol

from sdk.types import RequirementSpec

from ..context import DialogTemplateContext
from .patches import apply_requirement_patches


class RequirementSource(Protocol):
    """Data needed to pass a requirement leaf through SDK patches."""

    id: str
    priority: float
    enabled: bool

    def requirement_text(self, context: DialogTemplateContext) -> str: ...


def resolve_requirement_specs(
    sections: Sequence[RequirementSource],
    context: DialogTemplateContext,
) -> list[RequirementSpec]:
    # Feature-disabled rules were absent in the old patch input. Preserve that
    # boundary: patching one is a no-op, while add_requirements may introduce it.
    specs = [
        RequirementSpec(section.id, section.requirement_text(context), section.priority)
        for section in sections
        if section.enabled
    ]
    return apply_requirement_patches(specs, context.output_contract_patches)
