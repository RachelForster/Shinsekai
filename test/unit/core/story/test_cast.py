from __future__ import annotations

from dataclasses import replace
from itertools import permutations

import pytest

from core.story import (
    CandidateQuery,
    CastConstraints,
    CastFallback,
    CastMode,
    CastPolicy,
    CastResolutionContext,
    CastResolutionError,
    CastResolver,
    CharacterRuntimeStatus,
    ConditionSpec,
    RequiredRole,
    parse_story_project,
)

from .story_fixtures import campus_mystery_source


@pytest.fixture
def registry():
    return parse_story_project(campus_mystery_source()).character_registry


def test_fixed_cast_contains_only_required_characters(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.FIXED,
        required=("ling",),
        constraints=CastConstraints(min_active=1, max_active=4),
    )

    result = CastResolver().resolve(
        registry,
        policy,
        CastResolutionContext(current_cast=("detective-zhou",)),
    )

    assert result.active_character_ids == ("ling",)


def test_role_based_cast_prefers_declared_character(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.ROLE_BASED,
        required=("ling",),
        required_roles=(RequiredRole("authority", prefer=("detective-zhou",)),),
        constraints=CastConstraints(min_active=2, max_active=2),
    )

    result = CastResolver().resolve(registry, policy)

    assert result.active_character_ids == ("ling", "detective-zhou")
    assert result.role_bindings == {"authority": "detective-zhou"}


def test_required_roles_respect_candidate_location_filter(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.ROLE_BASED,
        required=("ling",),
        required_roles=(RequiredRole("authority"),),
        optional_query=CandidateQuery(
            conditions=(ConditionSpec("sameLocationAs", ("player",)),),
        ),
        constraints=CastConstraints(min_active=2, max_active=2),
    )

    with pytest.raises(CastResolutionError) as exc_info:
        CastResolver().resolve(
            registry,
            policy,
            CastResolutionContext(
                statuses={
                    "ling": CharacterRuntimeStatus(location="school"),
                    "detective-zhou": CharacterRuntimeStatus(location="station"),
                },
                player_location="school",
            ),
        )

    assert exc_info.value.code == "cast.missing_role"


def test_optional_query_does_not_filter_required_character(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.DYNAMIC,
        required=("ling",),
        optional_query=CandidateQuery(
            any_tags=("police",),
            conditions=(
                ConditionSpec("available", (True,)),
                ConditionSpec("alive", (True,)),
                ConditionSpec("sameLocationAs", ("player",)),
            ),
        ),
        constraints=CastConstraints(min_active=2, max_active=2),
    )
    statuses = {
        "ling": CharacterRuntimeStatus(location="school"),
        "detective-zhou": CharacterRuntimeStatus(location="school"),
    }

    result = CastResolver().resolve(
        registry,
        policy,
        CastResolutionContext(statuses=statuses, player_location="school"),
    )

    assert result.active_character_ids == ("ling", "detective-zhou")


def test_required_unavailable_character_fails_closed(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.FIXED,
        required=("ling",),
        constraints=CastConstraints(min_active=1, max_active=2),
    )

    with pytest.raises(CastResolutionError) as exc_info:
        CastResolver().resolve(
            registry,
            policy,
            CastResolutionContext(
                statuses={"ling": CharacterRuntimeStatus(available=False)}
            ),
        )

    assert exc_info.value.code == "cast.required_unavailable"


def test_invalid_ai_proposal_is_rejected(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.DYNAMIC,
        constraints=CastConstraints(min_active=0, max_active=2),
        selection=replace(CastPolicy().selection, allow_ai_proposal=True),
    )

    with pytest.raises(CastResolutionError) as exc_info:
        CastResolver().resolve(
            registry,
            policy,
            CastResolutionContext(ai_proposal=("ghost",)),
        )

    assert exc_info.value.code == "cast.invalid_ai_proposal"


def test_missing_role_can_use_explicit_fallback(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.ROLE_BASED,
        required=("ling",),
        required_roles=(RequiredRole("doctor"),),
        constraints=CastConstraints(min_active=1, max_active=2),
        fallback=CastFallback(on_missing_role="use-narrator"),
    )

    result = CastResolver().resolve(registry, policy)

    assert result.active_character_ids == ("ling", "detective-zhou")
    assert result.unresolved_roles == ("doctor",)


def test_resolution_order_is_stable(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.MIXED,
        constraints=CastConstraints(min_active=0, max_active=2),
    )
    resolver = CastResolver()

    results = {
        resolver.resolve(registry, policy).active_character_ids for _ in range(20)
    }

    assert results == {("ling", "detective-zhou")}


def test_resolution_is_independent_of_registry_iteration_order(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.DYNAMIC,
        constraints=CastConstraints(min_active=0, max_active=2),
    )

    results = {
        CastResolver()
        .resolve(replace(registry, characters=characters), policy)
        .active_character_ids
        for characters in permutations(registry.characters)
    }

    assert results == {("ling", "detective-zhou")}


def test_resolution_returns_application_readiness_plan(registry) -> None:
    policy = CastPolicy(
        mode=CastMode.FIXED,
        required=("ling",),
        constraints=CastConstraints(
            min_active=1,
            max_active=2,
            require_loaded_assets=True,
        ),
        fallback=CastFallback(on_load_failure="continue-without-optional"),
    )

    plan = CastResolver().resolve(registry, policy)

    assert plan.active_character_ids == ("ling",)
    assert plan.required_character_ids == ("ling",)
    assert plan.requires_loaded_assets is True
    assert plan.on_load_failure == "continue-without-optional"
