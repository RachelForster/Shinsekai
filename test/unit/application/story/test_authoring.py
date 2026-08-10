from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from application.story.authoring import (
    StoryAuthoringError,
    StoryAuthoringService,
    StoryProjectRepository,
    _save_compatibility,
)
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


def test_flag_off_prevents_authoring_storage_creation(tmp_path: Path) -> None:
    flags = FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: False})

    with pytest.raises(Exception, match="disabled"):
        StoryProjectRepository(flags, tmp_path / "projects")
    assert not (tmp_path / "projects").exists()
