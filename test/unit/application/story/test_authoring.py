from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import json

import pytest

from application.story.authoring import (
    StoryAuthoringError,
    StoryAuthoringService,
    StoryProjectRepository,
    _save_compatibility,
    import_generation_task_for_state,
)
from application.story.generation import StoryGenerationError
from application.story.project_loader import load_story_project
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from test.unit.core.story.story_fixtures import campus_mystery_source


def enabled_flags() -> FeatureFlagConfigManager:
    return FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: True})


def story_source() -> dict[str, Any]:
    source = campus_mystery_source()
    source["status"] = "draft"
    return source


class PatchModel:
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert request["region"] == "node:truth-ending"
        return {
            "operations": [
                {
                    "op": "replace-node",
                    "nodeId": "truth-ending",
                    "value": {
                        **request["selectedSource"],
                        "title": "AI revised ending",
                    },
                }
            ]
        }


class WholeStoryRepairModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        assert request["operation"] == "repair-story"
        assert any(
            item["code"] == "rule.missing_port" for item in request["repairPlan"]
        )
        assert request["generationGuides"]["logic"]["nodeTypeCatalog"]
        assert request["constraints"]["operationsOnly"] is True
        assert "story" not in request["responseSchema"]
        return {
            "baseVersion": request["baseVersion"],
            "operations": [
                {
                    "op": "replace",
                    "path": "/logicGraph/edges/0/to/port",
                    "value": "input",
                }
            ],
        }


class TruncatedThenPatchRepairModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise StoryGenerationError(
                "generation.model_json_invalid",
                "story author returned invalid JSON; response appears truncated",
            )
        assert "generation.model_json_invalid" in request["previousResponseError"]
        assert request["constraints"]["operationsOnly"] is True
        return {
            "baseVersion": request["baseVersion"],
            "operations": [
                {
                    "op": "replace",
                    "path": "/logicGraph/edges/0/to/port",
                    "value": "input",
                }
            ],
        }


def service_at(tmp_path: Path, *, model: Any = None) -> StoryAuthoringService:
    flags = enabled_flags()
    return StoryAuthoringService(
        flags,
        StoryProjectRepository(flags, tmp_path),
        author_model=model,
    )


def test_versioned_patch_diff_validation_and_undo(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    document = service.import_source(story_source())
    assert service.project_directory("campus-mystery") == tmp_path / "campus-mystery"
    assert (service.project_directory("campus-mystery") / "manifest.json").is_file()
    assert document["manifest"]["id"] == "campus-mystery"
    assert service.playable_story_path("campus-mystery") == tmp_path / "campus-mystery"
    assert load_story_project(service.playable_story_path("campus-mystery")).id == (
        "campus-mystery"
    )

    preview = service.apply_patch(
        "campus-mystery",
        {
            "operations": [
                {
                    "op": "replace-node",
                    "nodeId": "truth-ending",
                    "value": {
                        **document["source"]["narrativeGraph"]["nodes"][2],
                        "title": "Edited truth",
                    },
                }
            ]
        },
        base_revision=1,
        commit=False,
    )
    assert preview["committed"] is False
    assert preview["validation"]["valid"] is True
    assert any(item["path"].endswith("/title") for item in preview["diff"])
    assert service.get("campus-mystery")["manifest"]["draftRevision"] == 1

    committed = service.apply_patch(
        "campus-mystery",
        {"operations": preview["diff"][:0] or preview_patch_operations(preview)},
        base_revision=1,
        commit=True,
    )
    assert committed["document"]["manifest"]["draftRevision"] == 2
    assert (
        committed["document"]["source"]["narrativeGraph"]["nodes"][2]["title"]
        == "Edited truth"
    )

    undone = service.undo("campus-mystery", base_revision=2)
    assert undone["manifest"]["draftRevision"] == 3
    assert undone["source"]["narrativeGraph"]["nodes"][2]["title"] != "Edited truth"


def preview_patch_operations(preview: Mapping[str, Any]) -> list[dict[str, Any]]:
    ending = preview["source"]["narrativeGraph"]["nodes"][2]
    return [{"op": "replace-node", "nodeId": "truth-ending", "value": ending}]


def test_stale_revision_is_rejected_without_overwrite(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.import_source(story_source())
    patch = {
        "operations": [
            {
                "op": "replace-node",
                "nodeId": "truth-ending",
                "value": {
                    **story_source()["narrativeGraph"]["nodes"][2],
                    "title": "First edit",
                },
            }
        ]
    }
    service.apply_patch("campus-mystery", patch, base_revision=1, commit=True)

    with pytest.raises(StoryAuthoringError, match="expected draft revision 1"):
        service.apply_patch("campus-mystery", patch, base_revision=1, commit=True)


def test_graph_cast_and_specific_ending_preview_are_deterministic(
    tmp_path: Path,
) -> None:
    service = service_at(tmp_path)
    service.import_source(story_source())

    graph = service.graph_projection("campus-mystery")
    assert graph["diagnostics"] == []
    assert graph["sourceMap"]["node:old-school-gate"].endswith("nodes[1]")
    assert {edge["to"] for edge in graph["narrative"]["edges"]} == {
        "old-school-gate",
        "truth-ending",
    }

    cast = service.preview_cast("campus-mystery", "old-school-gate")
    assert cast["valid"] is True
    assert cast["activeCharacterIds"] == ["ling", "detective-zhou"]
    assert any(item["reasonCode"] == "selected" for item in cast["candidates"])

    preview = service.preview_path("campus-mystery", ending_id="truth-ending")
    assert preview["branchId"].startswith("editor-test-")
    assert preview["finalState"]["currentNodeId"] == "truth-ending"
    assert len(preview["snapshots"]) == 3


def test_ai_patch_is_previewed_before_explicit_commit(tmp_path: Path) -> None:
    service = service_at(tmp_path, model=PatchModel())
    service.import_source(story_source())

    proposal = service.propose_ai_patch(
        "campus-mystery",
        base_revision=1,
        region="node:truth-ending",
        instruction="Make the ending clearer",
    )

    assert proposal["committed"] is False
    assert (
        proposal["source"]["narrativeGraph"]["nodes"][2]["title"] == "AI revised ending"
    )
    assert service.get("campus-mystery")["manifest"]["draftRevision"] == 1


def test_repair_with_ai_fixes_semantic_targets_and_logic_graph(tmp_path: Path) -> None:
    model = WholeStoryRepairModel()
    service = service_at(tmp_path, model=model)
    source = story_source()
    source["variables"]["trust.ling"]["allowSemanticInput"] = False
    source["logicGraph"]["edges"][0]["to"]["port"] = "missing-input"
    service.import_source(source)

    repaired = service.repair_with_ai("campus-mystery", base_revision=1)

    assert model.calls == 1
    assert repaired["manifest"]["draftRevision"] == 2
    assert repaired["validation"]["valid"] is True
    assert repaired["source"]["variables"]["trust.ling"][
        "allowSemanticInput"
    ] is True
    assert repaired["source"]["logicGraph"]["edges"][0]["to"]["port"] == "input"


def test_repair_retries_truncated_model_json_with_compact_patch(tmp_path: Path) -> None:
    model = TruncatedThenPatchRepairModel()
    service = service_at(tmp_path, model=model)
    source = story_source()
    source["logicGraph"]["edges"][0]["to"]["port"] = "missing-input"
    service.import_source(source)

    repaired = service.repair_with_ai("campus-mystery", base_revision=1)

    assert model.calls == 2
    assert repaired["validation"]["valid"] is True
    assert repaired["source"]["logicGraph"]["edges"][0]["to"]["port"] == "input"


def test_repair_skips_llm_when_semantic_target_fix_is_sufficient(
    tmp_path: Path,
) -> None:
    service = service_at(tmp_path)
    source = story_source()
    source["variables"]["trust.ling"]["allowSemanticInput"] = False
    service.import_source(source)

    repaired = service.repair_with_ai("campus-mystery", base_revision=1)

    assert repaired["manifest"]["draftRevision"] == 2
    assert repaired["validation"]["valid"] is True


def test_repair_redirects_boolean_semantic_target_without_llm(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    source = story_source()
    source["semanticSignals"][0]["effectsByStrength"]["strong"] = [
        {"set": ["flags.arrived_old_school", True]}
    ]
    service.import_source(source)

    repaired = service.repair_with_ai("campus-mystery", base_revision=1)

    assert repaired["manifest"]["draftRevision"] == 2
    assert repaired["validation"]["valid"] is True
    effect = repaired["source"]["semanticSignals"][0]["effectsByStrength"]["strong"][0]
    assert effect == {"set": ["semantic.flags.arrived_old_school", 1]}
    assert repaired["source"]["variables"]["flags.arrived_old_school"]["type"] == "boolean"


def test_publish_creates_immutable_version_resources_and_save_contract(
    tmp_path: Path,
) -> None:
    service = service_at(tmp_path)
    service.import_source(story_source())

    published = service.publish("campus-mystery", base_revision=1)

    assert published["version"] == 1
    assert published["sourceHash"]
    assert Path(published["path"]).is_file()
    assert published["resourceDependencies"]["characters"][0]["characterId"] == "ling"
    assert published["saveCompatibility"]["compatibleWithPrevious"] is True
    playable = service.playable_story_path("campus-mystery")
    assert playable == tmp_path / "campus-mystery" / "published" / "v1"
    assert load_story_project(playable).id == "campus-mystery"
    assert load_story_project(Path(published["path"])).id == "campus-mystery"

    second = service.publish("campus-mystery", base_revision=1)
    first_source = service.repository.load_published("campus-mystery", 1)
    second_source = service.repository.load_published("campus-mystery", 2)
    assert second["version"] == 2
    assert first_source is not None and first_source["version"] == 1
    assert second_source is not None and second_source["version"] == 2


def test_save_compatibility_detects_removed_state_and_nodes() -> None:
    previous = story_source()
    current = deepcopy(previous)
    del current["variables"]["inventory"]
    current["narrativeGraph"]["nodes"].pop()

    report = _save_compatibility(previous, current, "hash")

    assert report["compatibleWithPrevious"] is False
    assert {item["code"] for item in report["breakingChanges"]} == {
        "variable.removed",
        "node.removed",
    }


def test_repeated_undo_walks_backward_through_history(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.import_source(story_source())
    first = service.apply_patch(
        "campus-mystery",
        {
            "operations": [
                {
                    "op": "replace-node",
                    "nodeId": "truth-ending",
                    "value": {
                        **story_source()["narrativeGraph"]["nodes"][2],
                        "title": "Revision B",
                    },
                }
            ]
        },
        base_revision=1,
        commit=True,
    )
    service.apply_patch(
        "campus-mystery",
        {
            "operations": [
                {
                    "op": "replace-node",
                    "nodeId": "truth-ending",
                    "value": {
                        **first["source"]["narrativeGraph"]["nodes"][2],
                        "title": "Revision C",
                    },
                }
            ]
        },
        base_revision=2,
        commit=True,
    )

    undone_b = service.undo("campus-mystery", base_revision=3)
    undone_a = service.undo("campus-mystery", base_revision=4)

    assert undone_b["source"]["narrativeGraph"]["nodes"][2]["title"] == "Revision B"
    assert undone_a["source"]["narrativeGraph"]["nodes"][2]["title"] == "雨声之后"


def test_import_and_publish_copy_story_scoped_character_files(tmp_path: Path) -> None:
    service = service_at(tmp_path / "projects")
    source = story_source()
    source["cast"]["characters"][0]["source"] = {
        "type": "author-generated",
        "path": "characters/ling.yaml",
    }
    service.import_source(source)
    generated = tmp_path / "generated"
    (generated / "characters").mkdir(parents=True)
    (generated / "characters" / "ling.yaml").write_text(
        "name: Ling\ncharacterSetting: Companion\n", encoding="utf-8"
    )
    (generated / "characters" / "detective-zhou.yaml").write_text(
        "name: Zhou\ncharacterSetting: Investigator\n", encoding="utf-8"
    )
    service.repository.copy_story_scoped_resources("campus-mystery", generated, source)

    project_dir = tmp_path / "projects" / "campus-mystery"
    assert (project_dir / "characters" / "ling.yaml").is_file()
    assert (project_dir / "characters" / "detective-zhou.yaml").is_file()

    published = service.publish("campus-mystery", base_revision=1)
    published_dir = Path(published["path"]).parent
    assert (published_dir / "characters" / "ling.yaml").is_file()
    assert (published_dir / "characters" / "detective-zhou.yaml").is_file()
    assert (published_dir / ".complete").is_file()


def test_import_generation_task_copies_character_profiles(tmp_path: Path) -> None:
    flags = enabled_flags()
    task_id = "gen-1"
    task_dir = tmp_path / "generation" / task_id
    (task_dir / "characters").mkdir(parents=True)
    source = story_source()
    source["cast"]["characters"][0]["source"] = {
        "type": "author-generated",
        "path": "characters/ling.yaml",
    }
    (task_dir / "draft.json").write_text(json.dumps(source), encoding="utf-8")
    (task_dir / "characters" / "ling.yaml").write_text(
        "name: Ling\ncharacterSetting: Companion\n", encoding="utf-8"
    )

    class Repository:
        def task_directory(self, _task_id: str) -> Path:
            return task_dir.resolve()

    class Generation:
        repository = Repository()

        def get(self, _task_id: str) -> dict[str, Any]:
            draft_path = str(task_dir.resolve() / "draft.json")
            return {"status": "succeeded", "draftPath": draft_path}

    project_root = tmp_path / "project"
    state = SimpleNamespace(
        config_manager=SimpleNamespace(feature_flags=flags),
        project_root_dir=str(project_root),
        story_generation_service=Generation(),
    )
    document = import_generation_task_for_state(state, task_id)
    copied = (
        project_root
        / "data"
        / "stories"
        / "projects"
        / "campus-mystery"
        / "characters"
        / "ling.yaml"
    )
    assert document["manifest"]["id"] == "campus-mystery"
    assert copied.is_file()


def test_import_failed_generation_task_with_draft(tmp_path: Path) -> None:
    flags = enabled_flags()
    task_id = "gen-failed"
    task_dir = tmp_path / "generation" / task_id
    task_dir.mkdir(parents=True)
    source = story_source()
    (task_dir / "draft.json").write_text(json.dumps(source), encoding="utf-8")

    class Repository:
        def task_directory(self, _task_id: str) -> Path:
            return task_dir.resolve()

    class Generation:
        repository = Repository()

        def get(self, _task_id: str) -> dict[str, Any]:
            return {
                "status": "failed",
                "draftPath": str(task_dir.resolve() / "draft.json"),
            }

    project_root = tmp_path / "project"
    state = SimpleNamespace(
        config_manager=SimpleNamespace(feature_flags=flags),
        project_root_dir=str(project_root),
        story_generation_service=Generation(),
    )
    document = import_generation_task_for_state(state, task_id)
    assert document["manifest"]["id"] == "campus-mystery"


def test_interrupted_publication_can_be_retried(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.import_source(story_source())
    leftover = tmp_path / "campus-mystery" / "published" / "v1"
    leftover.mkdir(parents=True)
    (leftover / "story.json").write_text("{}", encoding="utf-8")

    published = service.publish("campus-mystery", base_revision=1)

    assert published["version"] == 1
    assert Path(published["path"]).is_file()
    payload = Path(published["path"]).read_text(encoding="utf-8")
    assert '"id": "campus-mystery"' in payload


def test_pending_draft_commit_is_applied_on_load(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.import_source(story_source())
    directory = tmp_path / "campus-mystery"
    live = service.repository.load("campus-mystery")
    next_source = deepcopy(live["source"])
    next_source["title"] = "Recovered title"
    staging = directory / ".commit"
    staging.mkdir()
    (staging / "draft.json").write_text(
        json.dumps(next_source), encoding="utf-8"
    )
    next_manifest = {
        **live["manifest"],
        "draftRevision": 2,
        "undoCursor": 2,
        "title": "Recovered title",
    }
    (staging / "manifest.json").write_text(
        json.dumps(next_manifest), encoding="utf-8"
    )
    (staging / "ready").write_text("1", encoding="utf-8")

    recovered = service.get("campus-mystery")

    assert recovered["manifest"]["draftRevision"] == 2
    assert recovered["source"]["title"] == "Recovered title"
    assert not staging.exists()


class RoguePatchModel:
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "operations": [
                {
                    "op": "replace-node",
                    "nodeId": "truth-ending",
                    "value": {**request["selectedSource"], "title": "Scoped"},
                },
                {
                    "op": "replace",
                    "path": "/variables/trust.ling/initial",
                    "value": 99,
                },
            ]
        }


def test_ai_patch_rejects_operations_outside_selected_region(tmp_path: Path) -> None:
    service = service_at(tmp_path, model=RoguePatchModel())
    service.import_source(story_source())

    with pytest.raises(StoryAuthoringError, match="outside authoring region"):
        service.propose_ai_patch(
            "campus-mystery",
            base_revision=1,
            region="node:truth-ending",
            instruction="Rewrite only this ending",
        )


def test_flag_off_prevents_authoring_storage_creation(tmp_path: Path) -> None:
    flags = FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: False})

    with pytest.raises(Exception, match="disabled"):
        StoryProjectRepository(flags, tmp_path / "projects")
    assert not (tmp_path / "projects").exists()
