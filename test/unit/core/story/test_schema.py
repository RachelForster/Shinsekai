from __future__ import annotations

from pathlib import Path

import pytest

from core.story import (
    CastMode,
    StoryProjectLoader,
    StoryValidationError,
    VariableType,
    load_story_project,
    parse_story_project,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "fixtures" / "stories" / "campus-mystery"
)


def test_load_multifile_story_project() -> None:
    project = load_story_project(FIXTURE_ROOT)

    assert project.id == "campus-mystery"
    assert project.narrative_graph.start_node_id == "transfer-day"
    assert project.variables_by_id["trust.ling"].type == VariableType.INTEGER
    assert project.character_registry.initial_cast == ("ling",)
    assert set(project.character_registry.by_id) == {"ling", "detective-zhou"}
    gate = project.narrative_graph.by_id["old-school-gate"]
    assert gate.enter_when.op == "gte"
    assert gate.cast_policy.mode == CastMode.ROLE_BASED
    assert gate.cast_policy.required_roles[0].role == "authority"
    assert gate.choices[0].effects[0].op == "remove-set"


def test_loader_accepts_manifest_file_path() -> None:
    from_directory = load_story_project(FIXTURE_ROOT)
    from_manifest = StoryProjectLoader().load(FIXTURE_ROOT / "manifest.yaml")

    assert from_manifest == from_directory


def test_loader_rejects_reference_outside_story_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.yaml"
    outside.write_text("variables: {}\n", encoding="utf-8")
    story_root = tmp_path / "story"
    story_root.mkdir()
    (story_root / "manifest.yaml").write_text(
        """
schemaVersion: 1
id: path-test
version: 1
title: Path test
startNodeId: start
variablesRef: ../outside.yaml
narrativeGraph:
  startNodeId: start
  nodes:
    - id: start
      title: Start
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(StoryValidationError) as exc_info:
        load_story_project(story_root)

    assert exc_info.value.diagnostics[0].code == "schema.path_escape"


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


def test_loader_merges_chapter_node_documents(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        """
schemaVersion: 1
id: chapter-story
version: 1
title: Chapters
startNodeId: start
chaptersRef: [chapter-1.yaml]
narrativeGraph:
  startNodeId: start
  nodes: []
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "chapter-1.yaml").write_text(
        """
nodes:
  - id: start
    title: Start
""".strip(),
        encoding="utf-8",
    )

    project = load_story_project(tmp_path)

    assert [node.id for node in project.narrative_graph.nodes] == ["start"]


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
