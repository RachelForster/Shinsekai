from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.story import StoryProjectLoader, load_story_project
from core.story import CastMode, StoryValidationError, VariableType
from test.unit.core.story.story_fixtures import campus_mystery_source


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


def test_loader_rejects_windows_drive_reference(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(
        """
schemaVersion: 1
id: path-test
version: 1
title: Path test
startNodeId: start
variablesRef: 'C:\\outside.yaml'
narrativeGraph:
  startNodeId: start
  nodes:
    - id: start
      title: Start
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(StoryValidationError) as exc_info:
        load_story_project(tmp_path)

    assert exc_info.value.diagnostics[0].code == "schema.path_escape"


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


def test_loader_reads_authoring_json_documents(tmp_path: Path) -> None:
    source = campus_mystery_source()
    draft_root = tmp_path / "draft-project"
    draft_root.mkdir()
    (draft_root / "draft.json").write_text(json.dumps(source), encoding="utf-8")

    from_directory = load_story_project(draft_root)
    from_file = load_story_project(draft_root / "draft.json")
    assert from_directory.id == "campus-mystery"
    assert from_file == from_directory

    published_root = tmp_path / "published"
    published_root.mkdir()
    (published_root / "story.json").write_text(json.dumps(source), encoding="utf-8")
    assert load_story_project(published_root).id == "campus-mystery"
