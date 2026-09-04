"""Bridge requirement sections to the existing SDK patch protocol."""

from collections.abc import Sequence
from dataclasses import replace

from sdk.types import RequirementSpec

from ..context import DialogTemplateContext
from ..sections.requirement import RequirementSection
from .patches import apply_requirement_patches


def resolve_requirement_specs(
    sections: Sequence[RequirementSection],
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


def resolve_requirement_sections(
    sections: Sequence[RequirementSection],
    context: DialogTemplateContext,
) -> tuple[RequirementSection, ...]:
    """Apply SDK patches while keeping requirements as Composite leaf nodes."""
    specs = resolve_requirement_specs(sections, context)
    resolved = tuple(
        RequirementSection(
            id=spec.id,
            priority=spec.order,
            enabled=spec.enabled,
            resolved_text=spec.text,
        )
        for spec in specs
    )
    resolved_ids = {section.id for section in resolved}
    disabled = tuple(
        replace(section, enabled=False)
        for section in sections
        if section.id not in resolved_ids
    )
    return *resolved, *disabled
