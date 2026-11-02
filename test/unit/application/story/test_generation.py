from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import json
import os
import threading

import pytest
import yaml

from application.runtime.tasks import _create_task, _get_task
from application.story.generation import (
    ConfigStoryAuthorModel,
    StoryDraftValidator,
    StoryGenerationCancelled,
    StoryGenerationError,
    StoryGenerationRepository,
    StoryGenerationService,
    StoryGenerationStage,
    StoryPatchApplier,
    run_story_generation_background,
)
from application.story.generation_eval import (
    StoryGenerationEvalCase,
    StoryGenerationEvaluator,
)
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from core.story import parse_story_project
from test.unit.core.story.story_fixtures import campus_mystery_source


def enabled_flags() -> FeatureFlagConfigManager:
    return FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: True})


@pytest.mark.parametrize("failures", [2, 6])
def test_checkpoint_replace_retries_locks_and_preserves_original_on_failure(
    tmp_path, monkeypatch, failures
):
    repository = StoryGenerationRepository(enabled_flags(), tmp_path)
    path = tmp_path / "checkpoint.json"
    repository._write_json(path, {"version": 1})
    replace = os.replace
    calls = []

    def locked_replace(source, target):
        calls.append(target)
        if len(calls) <= failures:
            raise PermissionError("checkpoint is in use")
        replace(source, target)

    monkeypatch.setattr("application.story.generation.os.replace", locked_replace)
    monkeypatch.setattr("application.story.generation.time.sleep", lambda _: None)
    if failures == 6:
        with pytest.raises(PermissionError):
            repository._write_json(path, {"version": 2})
        assert repository._read_json(path) == {"version": 1}
        assert len(calls) == 6
    else:
        repository._write_json(path, {"version": 2})
        assert repository._read_json(path) == {"version": 2}
        assert len(calls) == 3
    assert not list(tmp_path.glob("*.tmp"))


def stage_artifacts(*, two_endings: bool = False) -> dict[str, dict[str, Any]]:
    source = campus_mystery_source()
    narrative = {
        "startNodeId": "school-gate",
        "nodes": [
            {
                "id": "school-gate",
                "title": "School gate",
                "type": "limited_turn_node",
                "instruction": "Ling invites the player to investigate the old school.",
                "maxRounds": 2,
                "transitions": [
                    {"to": "school-lobby", "when": "The player agrees to enter"}
                ],
                "defaultTo": "school-lobby",
            },
            {
                "id": "school-lobby",
                "title": "School lobby",
                "type": "free_chat_node",
                "instruction": "Let the player investigate and talk freely.",
                "transitions": [
                    {"to": "truth-ending", "when": "The player finds the truth"}
                ],
            },
            {
                "id": "truth-ending",
                "title": "Truth",
                "type": "ending_node",
            },
        ],
    }
    if two_endings:
        narrative["nodes"].append(
            {
                "id": "leave-ending",
                "title": "Leave",
                "type": "ending_node",
            }
        )
        narrative["nodes"][0]["transitions"].append(
            {"to": "leave-ending", "when": "The player refuses to enter"}
        )
    characters = deepcopy(source["cast"])
    for character in characters["characters"]:
        character["name"] = character["id"]
        character["responsibility"] = "Carries a required story role"
    return {
        "foundation": {
            "id": source["id"],
            "title": source["title"],
            "language": "zh-CN",
            "estimatedMinutes": 20,
            "assumptions": ["The player wants a mystery"],
            "premise": "A mystery at an old school building.",
            "themes": ["trust"],
            "worldRules": ["Evidence is physical"],
            "immutableFacts": ["Ling arrived first"],
            "secrets": ["The key is a replica"],
        },
        "characters": {"characters": characters["characters"]},
        "narrative": narrative,
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
        self.requests: list[Mapping[str, Any]] = []

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = str(request["operation"])
        if operation == "repair":
            raise AssertionError("valid fixture must not enter repair")
        stage = str(request["stage"])
        self.calls.append(stage)
        self.requests.append(request)
        if stage == self.fail_once_at and not self.failed:
            self.failed = True
            raise RuntimeError("transient model failure")
        return {"artifact": deepcopy(self.artifacts[stage])}


class RepairingModel(ScriptedModel):
    def __init__(self, artifacts: Mapping[str, Mapping[str, Any]]) -> None:
        super().__init__(artifacts)
        self.valid_opening = deepcopy(stage_artifacts()["narrative"]["nodes"][0])
        self.valid_opening["transitions"].append(
            {"to": "orphan-ending", "when": "The player leaves immediately"}
        )

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if request["operation"] == "repair":
            self.calls.append("repair")
            return {
                "baseVersion": request["baseVersion"],
                "operations": [
                    {
                        "op": "replace-node",
                        "nodeId": "school-gate",
                        "value": deepcopy(self.valid_opening),
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
    assert result["cost"]["requests"] == 3
    assert Path(result["draftPath"]).is_file()
    assert repository.load_artifact("story-task", StoryGenerationStage.FOUNDATION)[
        "secrets"
    ]
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    assert source["variables"] == {}
    assert source["semanticSignals"] == []
    assert source["logicGraph"] == {"version": 1, "nodes": [], "edges": []}
    assert source["cast"]["initialCast"] == [
        item["id"] for item in source["cast"]["characters"]
    ]
    assert all("castPolicy" not in node for node in source["narrativeGraph"]["nodes"])


def test_failed_task_resumes_from_latest_stage(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(), fail_once_at="narrative")
    service, repository = service_at(tmp_path, model)
    task = service.create("Resume this generation.", task_id="resume-task")

    with pytest.raises(RuntimeError, match="transient"):
        service.run(task["id"])
    failed = service.get(task["id"])
    assert failed["status"] == "failed"
    assert failed["currentStage"] == "narrative"
    assert failed["completedStages"] == ["foundation", "characters"]

    result = service.run(task["id"], resume=True)

    assert result["status"] == "succeeded"
    assert model.calls.count("foundation") == 1
    assert model.calls.count("narrative") == 2
    assert repository.load_artifact(task["id"], StoryGenerationStage.CHARACTERS)


def test_cancel_and_partial_regeneration_are_checkpoint_safe(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts())
    service, _ = service_at(tmp_path, model)
    task = service.create("Cancel after one checkpoint.", task_id="cancel-task")

    def cancel_after_first(update: Mapping[str, Any]) -> None:
        generated = update.get("generationTask", {})
        if generated.get("completedStages") == ["foundation"]:
            service.cancel(task["id"])

    with pytest.raises(StoryGenerationCancelled):
        service.run(task["id"], on_progress=cancel_after_first)
    cancelled = service.get(task["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["completedStages"] == ["foundation"]

    completed = service.run(task["id"], resume=True)
    assert completed["status"] == "succeeded"
    reset = service.regenerate_from(task["id"], StoryGenerationStage.NARRATIVE)
    assert reset["status"] == "queued"
    assert reset["completedStages"] == ["foundation", "characters"]
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

    with pytest.raises(StoryGenerationError, match="derived path"):
        applier.apply(
            source,
            {
                "baseVersion": 1,
                "operations": [
                    {"op": "replace", "path": "/cast/initialCast", "value": []}
                ],
            },
            base_version=1,
        )

    with pytest.raises(StoryGenerationError, match="derived path"):
        applier.apply(
            source,
            {
                "baseVersion": 1,
                "operations": [{"op": "replace", "path": "/metadata", "value": {}}],
            },
            base_version=1,
        )

    source["metadata"]["backgrounds"] = ["school-yard"]
    with pytest.raises(StoryGenerationError, match="derived path"):
        applier.apply(
            source,
            {
                "baseVersion": 1,
                "operations": [
                    {
                        "op": "replace",
                        "path": "/metadata/backgrounds",
                        "value": ["unknown-background"],
                    }
                ],
            },
            base_version=1,
        )


def test_directed_repair_loop_applies_only_a_bounded_patch(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"].append(
        {"id": "orphan-ending", "title": "Orphan", "type": "ending_node"}
    )
    model = RepairingModel(artifacts)
    service, _ = service_at(tmp_path, model)

    task = service.create("Repair an invalid cast reference.", task_id="repair-task")
    result = service.run(task["id"])

    assert result["status"] == "succeeded"
    assert result["repairAttempts"] == 1
    assert result["validation"]["valid"] is True
    assert model.calls[-1] == "repair"
    assert result["cost"]["requests"] == 4


def test_node_background_hints_can_use_new_locations(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    for node in artifacts["narrative"]["nodes"]:
        node["background"] = "unknown-background"
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create(
        "Use catalog backgrounds as optional location hints.",
        task_id="resource-task",
        resource_catalog={"backgrounds": [{"id": "known-background"}]},
    )

    assert service.run(task["id"])["validation"]["valid"]
    assert service.get(task["id"])["currentStage"] == "complete"


def test_character_stage_is_only_a_story_wide_list(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["characters"]["initialCast"] = ["ling"]
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create("Keep casting out of generation.", task_id="cast-list-task")

    with pytest.raises(StoryGenerationError, match="only accepts the story-wide list"):
        service.run(task["id"])
    assert service.get(task["id"])["currentStage"] == "characters"


def test_validator_detects_secret_leak() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][0]["exposedContext"] = {
        "hint": "The key is a replica"
    }
    report = StoryDraftValidator().validate(
        source, foundation={"secrets": ["The key is a replica"]}
    )

    assert report.valid is False
    assert "secret.exposed" in {item.code for item in report.issues}


def test_simple_node_instruction_can_reveal_a_foundation_secret(
    tmp_path: Path,
) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"][1][
        "instruction"
    ] = "The key is a replica. Reveal this after the player examines it."
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create("Reveal a secret later.", task_id="secret-reveal-task")

    result = service.run(task["id"])

    assert result["status"] == "succeeded"


def test_fixed_eval_reports_pass_rate_coverage_and_cost(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(two_endings=True))
    service, _ = service_at(tmp_path, model)
    evaluator = StoryGenerationEvaluator(enabled_flags(), service)

    report = evaluator.evaluate(
        (StoryGenerationEvalCase("one", "A synopsis", required_endings=2),)
    )

    assert report["structuralPassRate"] == 1
    assert report["meanEndingCoverage"] == 1
    assert report["generationCost"]["requests"] == 3


def test_flag_off_prevents_task_directory_creation(tmp_path: Path) -> None:
    flags = FeatureFlagConfigManager(overrides={FeatureFlag.STORY_SYSTEM: False})

    with pytest.raises(Exception, match="disabled"):
        StoryGenerationRepository(flags, tmp_path)
    assert list(tmp_path.iterdir()) == []


class NoOpRepairModel(ScriptedModel):
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if request["operation"] == "repair":
            self.calls.append("repair")
            return {
                "baseVersion": request["baseVersion"],
                "operations": [
                    {
                        "op": "replace",
                        "path": "/narrativeGraph/nodes/0/title",
                        "value": "Still broken",
                    }
                ],
            }
        return super().complete(request)


def test_author_model_uses_stateless_adapter_calls(monkeypatch) -> None:
    captured: list[list[dict[str, Any]]] = []

    class OpenAIAdapter:
        def chat(self, messages, stream=False, **kwargs):
            captured.append(json.loads(json.dumps(messages)))
            assert kwargs.get("response_format") == {"type": "json_object"}
            return {"artifact": {"ok": True}}

    manager = SimpleNamespace(
        llm_adapter=OpenAIAdapter(),
        chat=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("generation must not reuse LLMManager chat history")
        ),
    )
    model = ConfigStoryAuthorModel(enabled_flags(), config_manager=SimpleNamespace())
    monkeypatch.setattr(model, "_llm_manager", lambda: manager)

    first = model.complete({"synopsis": "task-a-secret", "stage": "foundation"})
    second = model.complete({"synopsis": "task-b-public", "stage": "foundation"})

    assert first["artifact"]["ok"] is True
    assert second["artifact"]["ok"] is True
    assert len(captured) == 2
    assert captured[0][0]["role"] == "system"
    assert "task-a-secret" in captured[0][1]["content"]
    assert "task-a-secret" not in captured[1][1]["content"]
    assert "task-b-public" in captured[1][1]["content"]
    assert len(captured[1]) == 2


def test_save_merges_cancel_requested_from_disk(tmp_path: Path) -> None:
    repository = StoryGenerationRepository(enabled_flags(), tmp_path)
    task = repository.create(
        {
            "id": "cancel-merge",
            "status": "running",
            "cancelRequested": False,
            "currentStage": "foundation",
        }
    )
    cancelled = dict(task)
    cancelled["cancelRequested"] = True
    repository.save(cancelled, preserve_cancel=False)
    stale = dict(task)
    stale["currentStage"] = "narrative"
    stale["cancelRequested"] = False
    saved = repository.save(stale)

    assert saved["cancelRequested"] is True
    assert saved["currentStage"] == "narrative"


def test_applied_repair_is_checkpointed_and_new_pass_gets_fresh_budget(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"].append(
        {"id": "orphan-ending", "title": "Orphan", "type": "ending_node"}
    )
    model = NoOpRepairModel(artifacts)
    service, repository = service_at(tmp_path, model)
    task = service.create("Checkpoint repairs.", task_id="repair-checkpoint")

    with pytest.raises(StoryGenerationError, match="did not pass validation"):
        service.run(task["id"])
    failed = service.get(task["id"])
    assert failed["repairAttempts"] == 3
    narrative = repository.load_artifact(task["id"], StoryGenerationStage.NARRATIVE)
    assert narrative["nodes"][0]["title"] == "Still broken"
    assert repository.load_draft(task["id"]) is not None

    model.calls.clear()
    with pytest.raises(StoryGenerationError, match="did not pass validation"):
        service.run(task["id"], resume=True)
    assert model.calls == ["repair", "repair", "repair"]
    assert service.get(task["id"])["repairAttempts"] == 6
    assert (
        repository.load_artifact(task["id"], StoryGenerationStage.NARRATIVE)["nodes"][
            0
        ]["title"]
        == "Still broken"
    )


def test_available_backgrounds_are_retained_without_bindings(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    for node in artifacts["narrative"]["nodes"]:
        node["background"] = "school-yard"
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create(
        "Choose a background while generating nodes.",
        task_id="binding-task",
        resource_catalog={"backgrounds": [{"name": "school-yard"}]},
    )
    result = service.run(task["id"])
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    project = parse_story_project(source)
    assert project.metadata.backgrounds == ("school-yard",)
    assert project.metadata.resource_bindings == {}
    assert {node.background for node in project.narrative_graph.nodes} == {
        "school-yard"
    }
    assert [request["resourceCatalog"] for request in model.requests] == [
        {},
        {},
        {"backgrounds": ["school-yard"]},
    ]


def test_background_failure_automatically_recovers_and_updates_snapshot(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(), fail_once_at="foundation")
    service, _ = service_at(tmp_path, model)
    generated = service.create("Show failure on the page.", task_id="ui-fail")
    state = SimpleNamespace(
        config_manager=SimpleNamespace(feature_flags=enabled_flags()),
        project_root_dir=str(tmp_path),
        story_generation_service=service,
        task_lock=threading.Lock(),
        tasks={},
    )
    bridge = _create_task(state, kind="story-generation", title="AI story compiler")

    result = run_story_generation_background(state, bridge["id"], generated["id"])
    assert result["validation"]["valid"]
    updated = _get_task(state, bridge["id"])
    assert updated["generationTask"]["status"] == "succeeded"
    assert updated["generationTask"]["currentStage"] == "complete"


def test_validator_detects_secret_in_title_and_choice_label() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][0]["title"] = "The key is a replica"
    source["narrativeGraph"]["nodes"][0]["choices"][0]["label"] = "The key is a replica"
    report = StoryDraftValidator().validate(
        source, foundation={"secrets": ["The key is a replica"]}
    )

    assert report.valid is False
    paths = {item.path for item in report.issues if item.code == "secret.exposed"}
    assert "/narrativeGraph/nodes/0/title" in paths
    assert "/narrativeGraph/nodes/0/choices/0/label" in paths


def test_regenerate_is_rejected_while_a_run_is_active(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts())
    service, _ = service_at(tmp_path, model)
    task = service.create("Reject concurrent regenerate.", task_id="lock-task")

    def reject_during_first_checkpoint(update: Mapping[str, Any]) -> None:
        generated = update.get("generationTask", {})
        if generated.get("completedStages") == ["foundation"]:
            with pytest.raises(StoryGenerationError, match="already running"):
                service.regenerate_from(task["id"], StoryGenerationStage.NARRATIVE)

    result = service.run(task["id"], on_progress=reject_during_first_checkpoint)
    assert result["status"] == "succeeded"


def test_author_generated_characters_are_materialized(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    for character in artifacts["characters"]["characters"]:
        character.pop("source", None)
        character["name"] = character["id"]
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create("Materialize author characters.", task_id="author-chars")
    result = service.run(task["id"])
    root = Path(result["draftPath"]).parent
    for character in artifacts["characters"]["characters"]:
        path = root / "characters" / f"{character['id']}.yaml"
        assert path.is_file()
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["name"] == character["id"]
        assert payload["sprites"] == []
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    assert source["cast"]["characters"][0]["source"]["path"] == "characters/ling.yaml"


def test_failed_eval_includes_spent_cost(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(), fail_once_at="narrative")
    service, _ = service_at(tmp_path, model)
    evaluator = StoryGenerationEvaluator(enabled_flags(), service)

    report = evaluator.evaluate(
        (StoryGenerationEvalCase("one", "A synopsis", required_endings=1),)
    )

    assert report["cases"][0]["passed"] is False
    assert report["generationCost"]["requests"] == 3
    assert report["generationCost"]["estimatedTokens"] > 0
