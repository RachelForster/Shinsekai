from __future__ import annotations

import pytest

from core.story import (
    CastResolutionContext,
    CastResolver,
    StoryValidationError,
    parse_story_project,
)

from .story_fixtures import campus_mystery_source


def test_parse_rejects_duplicate_narrative_node_ids() -> None:
    source = _minimal_source()
    source["narrativeGraph"]["nodes"].append({"id": "start", "title": "Duplicate"})

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    assert "schema.duplicate_id" in {item.code for item in exc_info.value.diagnostics}


def test_parse_rejects_unknown_inline_dsl_operator() -> None:
    source = _minimal_source()
    source["narrativeGraph"]["nodes"][0]["enterWhen"] = {"python": "x > 1"}

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    assert "condition.operator" in {item.code for item in exc_info.value.diagnostics}


def test_parse_rejects_candidate_predicate_in_narrative_condition() -> None:
    source = _minimal_source()
    source["narrativeGraph"]["nodes"][0]["enterWhen"] = {"available": True}

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    assert "condition.operator" in {item.code for item in exc_info.value.diagnostics}


def test_parse_rejects_narrative_condition_in_candidate_query() -> None:
    source = _minimal_source()
    source["narrativeGraph"]["nodes"][0]["castPolicy"] = {
        "mode": "dynamic",
        "optionalQuery": {
            "allConditions": [{"gte": ["missing.metric", 1]}],
        },
    }

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    assert "cast.condition_operator" in {
        item.code for item in exc_info.value.diagnostics
    }


def test_parse_normalizes_boolean_and_composite_conditions() -> None:
    source = _minimal_source()
    source["variables"] = {"flags.ready": {"type": "boolean", "initial": False}}
    source["narrativeGraph"]["nodes"][0]["enterWhen"] = {
        "all": [True, {"not": {"flag": "flags.ready"}}]
    }

    project = parse_story_project(source)
    condition = project.narrative_graph.nodes[0].enter_when

    assert condition.op == "all"
    assert condition.args[0].op == "true"
    assert condition.args[1].op == "not"
    assert condition.args[1].args[0].op == "flag"


def test_set_initial_values_are_normalized_to_immutable_tuple() -> None:
    source = _minimal_source()
    source["variables"] = {
        "inventory": {"type": "string_set", "initial": ["key", "photo"]}
    }

    project = parse_story_project(source)

    assert project.variables_by_id["inventory"].initial == ("key", "photo")


def test_cast_candidate_status_conditions_accept_boolean_values() -> None:
    source = _minimal_source()
    source["narrativeGraph"]["nodes"][0]["castPolicy"] = {
        "mode": "dynamic",
        "optionalQuery": {
            "allConditions": [
                {"available": True},
                {"alive": True},
                {"sameLocationAs": "player"},
            ]
        },
    }

    project = parse_story_project(source)
    conditions = project.narrative_graph.nodes[0].cast_policy.optional_query.conditions

    assert [(condition.op, condition.args) for condition in conditions] == [
        ("available", (True,)),
        ("alive", (True,)),
        ("sameLocationAs", ("player",)),
    ]


def test_parse_rejects_non_string_keys_and_non_json_context_values() -> None:
    source = _minimal_source()
    source["logicGraph"] = {
        "nodes": [
            {
                "id": "bad-config",
                "type": "on-choice",
                "config": {1: "a", "x": object()},
            }
        ]
    }
    source["narrativeGraph"]["nodes"][0]["exposedContext"] = {"invalid": float("nan")}

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    codes = {item.code for item in exc_info.value.diagnostics}
    assert "schema.mapping_key" in codes
    assert "schema.json_value" in codes


def test_parse_preserves_character_content_digest() -> None:
    source = _minimal_source()
    source["cast"] = {
        "characters": [
            {
                "id": "ling",
                "source": {
                    "type": "local-library",
                    "characterId": "ling",
                    "contentDigest": "sha256:test-ling",
                },
            }
        ]
    }

    project = parse_story_project(source)

    assert (
        project.character_registry.characters[0].source.content_digest
        == "sha256:test-ling"
    )


def test_parse_rejects_windows_drive_character_path() -> None:
    source = _minimal_source()
    source["cast"] = {
        "characters": [
            {
                "id": "outsider",
                "source": {
                    "type": "embedded",
                    "path": r"C:\outside.yaml",
                },
            }
        ]
    }

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    assert "character.path_escape" in {item.code for item in exc_info.value.diagnostics}


def test_registry_continuity_default_applies_to_node_policy() -> None:
    source = campus_mystery_source()
    source["cast"]["defaults"]["preserveCurrentCast"] = False
    source["narrativeGraph"]["nodes"][0]["castPolicy"] = {
        "mode": "dynamic",
        "constraints": {"minActive": 1, "maxActive": 1},
    }

    project = parse_story_project(source)
    policy = project.narrative_graph.nodes[0].cast_policy
    result = CastResolver().resolve(
        project.character_registry,
        policy,
        CastResolutionContext(current_cast=("detective-zhou",)),
    )

    assert policy.constraints.preserve_current_cast is False
    assert result.active_character_ids == ("ling",)


def test_parse_rejects_repeat_window_larger_than_retained_history() -> None:
    source = campus_mystery_source()
    source["semanticSignals"][0]["repeatWindow"] = 257

    with pytest.raises(StoryValidationError) as exc_info:
        parse_story_project(source)

    assert "schema.range" in {item.code for item in exc_info.value.diagnostics}


def _minimal_source() -> dict:
    return {
        "schemaVersion": 1,
        "id": "minimal-story",
        "version": 1,
        "title": "Minimal",
        "status": "draft",
        "startNodeId": "start",
        "variables": {},
        "cast": {},
        "narrativeGraph": {
            "startNodeId": "start",
            "nodes": [{"id": "start", "title": "Start"}],
        },
        "logicGraph": {},
    }
