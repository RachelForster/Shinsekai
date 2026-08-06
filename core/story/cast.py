"""Pure, deterministic cast resolution for story scenes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .models import CastMode, CastPolicy, CharacterDefinition, CharacterRegistry


@dataclass(frozen=True, slots=True)
class CharacterRuntimeStatus:
    available: bool = True
    alive: bool = True
    location: str | None = None
    loaded: bool = True


@dataclass(frozen=True, slots=True)
class CastResolutionContext:
    current_cast: tuple[str, ...] = ()
    statuses: Mapping[str, CharacterRuntimeStatus] = field(
        default_factory=lambda: MappingProxyType({})
    )
    player_location: str | None = None
    ai_proposal: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CastResolution:
    active_character_ids: tuple[str, ...]
    role_bindings: Mapping[str, str]
    excluded: Mapping[str, str]
    unresolved_roles: tuple[str, ...] = ()


class CastResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CastResolver:
    """Resolve a CastPolicy from registered and currently eligible characters."""

    def resolve(
        self,
        registry: CharacterRegistry,
        policy: CastPolicy,
        context: CastResolutionContext | None = None,
    ) -> CastResolution:
        context = context or CastResolutionContext()
        characters = registry.by_id
        excluded: dict[str, str] = {}
        eligible: dict[str, CharacterDefinition] = {}
        for character in registry.characters:
            reason = self._exclusion_reason(
                character,
                policy,
                context,
                apply_optional_query=False,
            )
            if reason is None:
                eligible[character.id] = character
            else:
                excluded[character.id] = reason
        optional_eligible: dict[str, CharacterDefinition] = {}
        for character in eligible.values():
            reason = self._exclusion_reason(
                character,
                policy,
                context,
                apply_optional_query=True,
            )
            if reason is None:
                optional_eligible[character.id] = character
            elif character.id not in policy.required:
                excluded[character.id] = reason

        active: list[str] = []
        for character_id in policy.required:
            if character_id not in characters:
                raise CastResolutionError(
                    "cast.unknown_character",
                    f"required character {character_id!r} is not registered",
                )
            if character_id not in eligible:
                raise CastResolutionError(
                    "cast.required_unavailable",
                    f"required character {character_id!r} is {excluded.get(character_id, 'ineligible')}",
                )
            if character_id not in active:
                active.append(character_id)

        role_bindings: dict[str, str] = {}
        unresolved_roles: list[str] = []
        for role_requirement in policy.required_roles:
            for slot in range(role_requirement.count):
                candidate = self._choose_for_role(
                    role_requirement.role,
                    role_requirement.prefer,
                    eligible,
                    active,
                    context,
                )
                if candidate is None:
                    if policy.fallback.on_missing_role == "error":
                        raise CastResolutionError(
                            "cast.missing_role",
                            f"no eligible character can satisfy role {role_requirement.role!r}",
                        )
                    unresolved_roles.append(role_requirement.role)
                    break
                active.append(candidate)
                binding_key = (
                    role_requirement.role
                    if role_requirement.count == 1
                    else f"{role_requirement.role}[{slot}]"
                )
                role_bindings[binding_key] = candidate

        if context.ai_proposal:
            if not policy.selection.allow_ai_proposal:
                raise CastResolutionError(
                    "cast.ai_proposal_disabled",
                    "AI cast proposal is not allowed by this policy",
                )
            invalid = [
                character_id
                for character_id in context.ai_proposal
                if character_id not in optional_eligible
                or character_id in policy.forbidden
            ]
            if invalid:
                raise CastResolutionError(
                    "cast.invalid_ai_proposal",
                    f"AI proposed ineligible characters: {', '.join(invalid)}",
                )

        if policy.mode != CastMode.FIXED:
            optional_order = self._optional_order(
                optional_eligible,
                active,
                policy,
                context,
            )
            for character_id in optional_order:
                if len(active) >= policy.constraints.max_active:
                    break
                active.append(character_id)

        if len(active) > policy.constraints.max_active:
            raise CastResolutionError(
                "cast.max_active",
                "required cast exceeds maxActive",
            )
        if len(active) < policy.constraints.min_active:
            raise CastResolutionError(
                "cast.min_active",
                "resolved cast does not satisfy minActive",
            )
        return CastResolution(
            active_character_ids=tuple(active),
            role_bindings=MappingProxyType(role_bindings),
            excluded=MappingProxyType(excluded),
            unresolved_roles=tuple(unresolved_roles),
        )

    def _exclusion_reason(
        self,
        character: CharacterDefinition,
        policy: CastPolicy,
        context: CastResolutionContext,
        *,
        apply_optional_query: bool,
    ) -> str | None:
        if character.id in policy.forbidden:
            return "forbidden"
        status = context.statuses.get(character.id, CharacterRuntimeStatus())
        if not status.available:
            return "unavailable"
        if not status.alive:
            return "dead"
        if policy.constraints.require_loaded_assets and not status.loaded:
            return "not-loaded"
        if not apply_optional_query:
            return None
        query = policy.optional_query
        if query.any_tags and not set(query.any_tags).intersection(character.tags):
            return "missing-any-tag"
        if query.all_tags and not set(query.all_tags).issubset(character.tags):
            return "missing-all-tags"
        for condition in query.conditions:
            if condition.op == "available" and status.available != bool(
                condition.args[0]
            ):
                return "availability-condition"
            if condition.op == "alive" and status.alive != bool(condition.args[0]):
                return "alive-condition"
            if condition.op == "sameLocationAs":
                reference = condition.args[0]
                if reference == "player":
                    expected_location = context.player_location
                else:
                    expected_location = context.statuses.get(
                        str(reference), CharacterRuntimeStatus()
                    ).location
                if expected_location is None or status.location != expected_location:
                    return "location-condition"
        return None

    @staticmethod
    def _choose_for_role(
        role: str,
        preferred: tuple[str, ...],
        eligible: Mapping[str, CharacterDefinition],
        active: list[str],
        context: CastResolutionContext,
    ) -> str | None:
        candidates = [
            character
            for character in eligible.values()
            if role in character.roles and character.id not in active
        ]
        preferred_index = {
            character_id: index for index, character_id in enumerate(preferred)
        }
        current_index = {
            character_id: index
            for index, character_id in enumerate(context.current_cast)
        }
        candidates.sort(
            key=lambda character: (
                preferred_index.get(character.id, len(preferred_index) + 1),
                current_index.get(character.id, len(current_index) + 1),
                -character.priority,
                character.id,
            )
        )
        return candidates[0].id if candidates else None

    @staticmethod
    def _optional_order(
        eligible: Mapping[str, CharacterDefinition],
        active: list[str],
        policy: CastPolicy,
        context: CastResolutionContext,
    ) -> tuple[str, ...]:
        candidates = [
            character for character in eligible.values() if character.id not in active
        ]
        proposal_index = {
            character_id: index
            for index, character_id in enumerate(context.ai_proposal)
        }
        current_index = {
            character_id: index
            for index, character_id in enumerate(context.current_cast)
        }
        candidates.sort(
            key=lambda character: (
                proposal_index.get(character.id, len(proposal_index) + 1),
                (
                    current_index.get(character.id, len(current_index) + 1)
                    if policy.constraints.preserve_current_cast
                    else 0
                ),
                -character.priority,
                character.id,
            )
        )
        return tuple(character.id for character in candidates)
