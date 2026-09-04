"""Apply SDK output-contract patches without coupling them to prompt sections."""

import logging
from collections.abc import Sequence

from sdk.types import (
    FieldPatch,
    OutputContractPatch,
    OutputFieldSpec,
    RequirementPatch,
    RequirementSpec,
)

logger = logging.getLogger(__name__)


def _apply_field_patch(field: OutputFieldSpec, patch: FieldPatch) -> OutputFieldSpec:
    desc = field.description
    if patch.description:
        desc = patch.description
    if patch.enum:
        enum_text = ", ".join(str(x) for x in patch.enum)
        desc = f"{desc} Allowed values: {enum_text}."
    return OutputFieldSpec(
        key=field.key,
        type=patch.type or field.type,
        description=desc,
        required=field.required if patch.required is None else bool(patch.required),
        aliases=field.aliases,
    )


def _apply_requirement_patch(
    requirement: RequirementSpec,
    patch: RequirementPatch,
) -> RequirementSpec:
    if patch.mode == "remove":
        return RequirementSpec(
            id=requirement.id,
            text=requirement.text,
            order=requirement.order,
            enabled=False,
        )
    if patch.mode == "replace":
        return RequirementSpec(
            id=requirement.id,
            text=patch.text,
            order=requirement.order,
            enabled=requirement.enabled,
        )
    if patch.mode == "prepend":
        return RequirementSpec(
            id=requirement.id,
            text=f"{patch.text} {requirement.text}".strip(),
            order=requirement.order,
            enabled=requirement.enabled,
        )
    if patch.mode == "append":
        return RequirementSpec(
            id=requirement.id,
            text=f"{requirement.text} {patch.text}".strip(),
            order=requirement.order,
            enabled=requirement.enabled,
        )
    logger.warning(
        "Unknown RequirementPatch.mode %r for requirement %s; leaving requirement unchanged",
        patch.mode,
        requirement.id,
    )
    return requirement


def apply_field_patches(
    fields: dict[str, OutputFieldSpec],
    contract_patches: Sequence[OutputContractPatch],
) -> dict[str, OutputFieldSpec]:
    fields = dict(fields)
    for patch in sorted(contract_patches, key=lambda p: p.priority):
        for key in patch.remove_fields:
            if key not in {"character_name", "speech", "sprite"}:
                fields.pop(key, None)
        for key, field_patch in patch.field_patches.items():
            existing = fields.get(key)
            if existing is not None:
                fields[key] = _apply_field_patch(existing, field_patch)
        for field in patch.add_fields:
            fields[field.key] = OutputFieldSpec(
                key=field.key,
                type=field.type,
                description=field.description,
                required=field.required,
                aliases=field.aliases,
            )
    return fields


def apply_requirement_patches(
    requirements: Sequence[RequirementSpec],
    contract_patches: Sequence[OutputContractPatch],
) -> list[RequirementSpec]:
    requirement_by_id = {item.id: item for item in requirements}
    for patch in sorted(contract_patches, key=lambda p: p.priority):
        for req_id, req_patch in patch.requirement_patches.items():
            if req_id in requirement_by_id:
                requirement_by_id[req_id] = _apply_requirement_patch(
                    requirement_by_id[req_id], req_patch
                )
        for req in patch.add_requirements:
            requirement_by_id[req.id] = req
    requirements = sorted(
        (item for item in requirement_by_id.values() if item.enabled),
        key=lambda item: item.order,
    )
    return requirements
