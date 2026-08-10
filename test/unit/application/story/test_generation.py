from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from application.story.generation import (
    StoryDraftValidator,
    StoryGenerationCancelled,
    StoryGenerationError,
    StoryGenerationRepository,
    StoryGenerationService,
    StoryGenerationStage,
    StoryPatchApplier,
)
from application.story.generation_eval import (
    StoryGenerationEvalCase,
    StoryGenerationEvaluator,
)
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from test.unit.core.story.story_fixtures import campus_mystery_source


def enabled_flags() -> FeatureFlagConfigManager:
    return FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: True})


def stage_artifacts(*, two_endings: bool = False) -> dict[str, dict[str, Any]]:
    source = campus_mystery_source()
    narrative = deepcopy(source["narrativeGraph"])
    if two_endings:
        narrative["nodes"].append(
            {
                "id": "leave-ending",
                "title": "Leave",
                "type": "ending",
                "commitment": "draft",
                "castPolicy": {
                    "mode": "fixed",
                    "required": ["ling"],
                    "constraints": {"minActive": 1, "maxActive": 2},
                    "fallback": {"onMissingRole": "error", "onLoadFailure": "error"},
                },
            }
        )
        narrative["nodes"][0]["choices"].append(
            {
                "id": "leave-now",
                "label": "Leave",
                "effects": [],
                "goto": "leave-ending",
            }
        )
    characters = deepcopy(source["cast"])
    for character in characters["characters"]:
        character["name"] = character["id"]
        character["responsibility"] = "Carries a required story role"
    return {
        "requirements": {
            "id": source["id"],
            "title": source["title"],
            "language": "zh-CN",
            "estimatedMinutes": 20,
            "assumptions": ["The player wants a mystery"],
            "requirements": {"endings": 2 if two_endings else 1},
        },
        "bible": {
            "premise": "A mystery at an old school building.",
            "themes": ["trust"],
            "worldRules": ["Evidence is physical"],
            "immutableFacts": ["Ling arrived first"],
            "secrets": ["The key is a replica"],
        },
        "characters": characters,
        "state": {
            "variables": deepcopy(source["variables"]),
            "semanticSignals": deepcopy(source["semanticSignals"]),
        },
        "narrative": narrative,
        "logic": deepcopy(source["logicGraph"]),
        "resources": {"bindings": {}, "unresolved": []},
    }


class ScriptedModel:
    def __init__(
        self,
        artifacts: Mapping[str, Mapping[str, Any]],
        *,
        fail_once_at: str = "",
    ) -> None:
        self.artifacts = deepcopy(dict(artifacts))
        self.fail_once_at = fail_once_at
        self.failed = False
        self.calls: list[str] = []

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = str(request["operation"])
        if operation == "repair":
            raise AssertionError("valid fixture must not enter repair")
        stage = str(request["stage"])
        self.calls.append(stage)
        if stage == self.fail_once_at and not self.failed:
            self.failed = True
            raise RuntimeError("transient model failure")
        return {"artifact": deepcopy(self.artifacts[stage])}


class RepairingModel(ScriptedModel):
    def __init__(self, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
        super().__init__(artifacts)
        self.valid_ending = deepcopy(stage_artifacts()["narrative"]["nodes"][2])

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if request["operation"] == "repair":
            self.calls.append("repair")
            return {
                "baseVersion": request["baseVersion"],
                "operations": [
                    {
                        "op": "replace-node",
                        "nodeId": "truth-ending",
                        "value": deepcopy(self.valid_ending),
                    }
                ],
            }
        return super().complete(request)


def service_at(
    root: Path, model: ScriptedModel
) -> tuple[StoryGenerationService, StoryGenerationRepository]:
    flags = enabled_flags()
    repository = StoryGenerationRepository(flags, root)
    return StoryGenerationService(flags, repository, model), repository


def test_pipeline_persists_intermediate_artifacts_and_compiled_draft(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(stage_artifacts())
    service, repository = service_at(tmp_path, model)

    task = service.create("Investigate the abandoned school.", task_id="story-task")
    result = service.run(task["id"])

    assert result["status"] == "succeeded"
    assert result["completedStages"] == [stage.value for stage in StoryGenerationStage]
    assert result["assumptions"] == ["The player wants a mystery"]
    assert result["validation"]["valid"] is True
    assert result["validation"]["endingCoverage"] == 1
    assert result["cost"]["requests"] == 7
    assert Path(result["draftPath"]).is_file()
    assert repository.load_artifact("story-task", StoryGenerationStage.BIBLE)["secrets"]


def test_failed_task_resumes_from_latest_stage(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(), fail_once_at="narrative")
    service, repository = service_at(tmp_path, model)
    task = service.create("Resume this generation.", task_id="resume-task")

    with pytest.raises(RuntimeError, match="transient"):
        service.run(task["id"])
    failed = service.get(task["id"])
    assert failed["status"] == "failed"
    assert failed["currentStage"] == "narrative"
    assert failed["completedStages"] == ["requirements", "bible", "characters", "state"]

    result = service.run(task["id"], resume=True)

    assert result["status"] == "succeeded"
    assert model.calls.count("requirements") == 1
    assert model.calls.count("narrative") == 2
    assert repository.load_artifact(task["id"], StoryGenerationStage.STATE)


def test_cancel_and_partial_regeneration_are_checkpoint_safe(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts())
    service, _ = service_at(tmp_path, model)
    task = service.create("Cancel after one checkpoint.", task_id="cancel-task")

    def cancel_after_first(update: Mapping[str, Any]) -> None:
        generated = update.get("generationTask", {})
        if generated.get("completedStages") == ["requirements"]:
            service.cancel(task["id"])

    with pytest.raises(StoryGenerationCancelled):
        service.run(task["id"], on_progress=cancel_after_first)
    cancelled = service.get(task["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["completedStages"] == ["requirements"]

    completed = service.run(task["id"], resume=True)
    assert completed["status"] == "succeeded"
    reset = service.regenerate_from(task["id"], StoryGenerationStage.NARRATIVE)
    assert reset["status"] == "queued"
    assert reset["completedStages"] == ["requirements", "bible", "characters", "state"]
    assert reset["draftPath"] == ""


def test_bounded_patch_rejects_escape_and_preserves_identity() -> None:
    source = campus_mystery_source()
    source["status"] = "draft"
    applier = StoryPatchApplier()

    updated = applier.apply(
        source,
        {
            "baseVersion": 1,
            "operations": [
                {
                    "op": "replace-node",
                    "nodeId": "truth-ending",
                    "value": {
                        **source["narrativeGraph"]["nodes"][2],
                        "title": "A repaired truth",
                    },
                }
            ],
        },
        base_version=1,
    )
    assert updated["version"] == 2
    assert updated["narrativeGraph"]["nodes"][2]["id"] == "truth-ending"
    assert updated["narrativeGraph"]["nodes"][2]["title"] == "A repaired truth"

    with pytest.raises(StoryGenerationError, match="cannot modify"):
        applier.apply(
            source,
            {"baseVersion": 1, "operations": [{"op": "remove", "path": "/id"}]},
            base_version=1,
        )


def test_directed_repair_loop_applies_only_a_bounded_patch(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"][2]["castPolicy"]["required"] = ["ghost"]
    model = RepairingModel(artifacts)
    service, _ = service_at(tmp_path, model)

    task = service.create("Repair an invalid cast reference.", task_id="repair-task")
    result = service.run(task["id"])

    assert result["status"] == "succeeded"
    assert result["repairAttempts"] == 1
    assert result["validation"]["valid"] is True
    assert model.calls[-1] == "repair"
    assert result["cost"]["requests"] == 8


def test_resource_bindings_must_use_supplied_catalog_ids(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["resources"]["bindings"] = {"openingBackground": "unknown-background"}
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create(
        "Bind only supplied resources.",
        task_id="resource-task",
        resource_catalog={"backgrounds": [{"id": "known-background"}]},
    )

    with pytest.raises(StoryGenerationError, match="not in the supplied catalog"):
        service.run(task["id"])
    assert service.get(task["id"])["currentStage"] == "resources"


def test_validator_detects_secret_leak() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][0]["exposedContext"] = {
        "hint": "The key is a replica"
    }
    report = StoryDraftValidator().validate(
        source, story_bible={"secrets": ["The key is a replica"]}
    )

    assert report.valid is False
    assert "secret.exposed" in {item.code for item in report.issues}


def test_fixed_eval_reports_pass_rate_coverage_and_cost(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(two_endings=True))
    service, _ = service_at(tmp_path, model)
    evaluator = StoryGenerationEvaluator(enabled_flags(), service)

    report = evaluator.evaluate(
        (StoryGenerationEvalCase("one", "A synopsis", required_endings=2),)
    )

    assert report["structuralPassRate"] == 1
    assert report["meanEndingCoverage"] == 1
    assert report["generationCost"]["requests"] == 7


def test_flag_off_prevents_task_directory_creation(tmp_path: Path) -> None:
    flags = FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: False})

    with pytest.raises(Exception, match="disabled"):
        StoryGenerationRepository(flags, tmp_path)
    assert list(tmp_path.iterdir()) == []
