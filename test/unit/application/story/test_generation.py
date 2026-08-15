from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import json
import threading

import pytest
import yaml

from application.runtime.tasks import _create_task, _get_task
from application.story.coordinator import apply_story_resource_bindings
from application.story.generation import (
    ConfigStoryAuthorModel,
    StoryDraftValidator,
    StoryGenerationCancelled,
    StoryGenerationError,
    StoryGenerationRepository,
    StoryGenerationService,
    StoryGenerationStage,
    StoryPatchApplier,
    _force_playable_source,
    _sanitize_generated_source,
    _stage_schema,
    _validate_logic,
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


def _title_case_id(value: str) -> str:
    return "-".join(
        part[:1].upper() + part[1:] if part else part for part in value.split("-")
    )


def test_uppercase_node_ids_are_normalized_without_repair(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    narrative = artifacts["narrative"]
    renamed = {node["id"]: _title_case_id(node["id"]) for node in narrative["nodes"]}
    narrative["startNodeId"] = renamed[narrative["startNodeId"]]
    for node in narrative["nodes"]:
        node["id"] = renamed[node["id"]]
        for choice in node.get("choices") or []:
            if choice.get("goto") in renamed:
                choice["goto"] = renamed[choice["goto"]]
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create("Normalize generated identifiers.", task_id="id-case")
    result = service.run(task["id"])
    assert result["status"] == "succeeded"
    assert result["repairAttempts"] == 0
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    assert source["narrativeGraph"]["startNodeId"] == "transfer-day"
    assert {node["id"] for node in source["narrativeGraph"]["nodes"]} == {
        "transfer-day",
        "old-school-gate",
        "truth-ending",
    }


def test_missing_ending_is_synthesized_without_repair(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"] = [
        node
        for node in artifacts["narrative"]["nodes"]
        if node.get("type") != "ending"
    ]
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create("Synthesize a reachable ending.", task_id="ending-fix")
    result = service.run(task["id"])
    assert result["status"] == "succeeded"
    assert result["repairAttempts"] == 0
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    assert any(
        node.get("type") == "ending" for node in source["narrativeGraph"]["nodes"]
    )
    report = StoryDraftValidator().validate(source)
    assert report.valid is True


def test_logic_stage_coerces_string_version_and_missing_collections() -> None:
    assert _stage_schema(StoryGenerationStage.LOGIC)["version"] == 1
    artifact: dict[str, Any] = {"version": "1"}
    _validate_logic(artifact)
    assert artifact == {"version": 1, "nodes": [], "edges": []}


def test_pipeline_accepts_string_logic_graph_version(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["logic"]["version"] = "1"
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create("Accept a string logic graph version.", task_id="logic-version")
    result = service.run(task["id"])
    assert result["status"] == "succeeded"
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    assert source["logicGraph"]["version"] == 1


def test_sanitize_keeps_unknown_required_cast_for_repair() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][2]["castPolicy"]["required"] = ["ghost"]
    sanitized = _sanitize_generated_source(source)
    assert sanitized["narrativeGraph"]["nodes"][2]["castPolicy"]["required"] == [
        "ghost"
    ]


def test_force_playable_replaces_unknown_required_cast() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][2]["castPolicy"]["required"] = ["ghost"]
    forced = _force_playable_source(source)
    assert forced["narrativeGraph"]["nodes"][2]["castPolicy"]["required"] == ["ling"]
    report = StoryDraftValidator().validate(forced)
    assert report.valid is True


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

    first = model.complete({"synopsis": "task-a-secret", "stage": "bible"})
    second = model.complete({"synopsis": "task-b-public", "stage": "bible"})

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
            "currentStage": "bible",
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


def test_applied_repair_is_checkpointed_before_attempt_count(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"][2]["castPolicy"]["required"] = ["ghost"]
    model = NoOpRepairModel(artifacts)
    service, repository = service_at(tmp_path, model)
    task = service.create("Checkpoint repairs.", task_id="repair-checkpoint")

    result = service.run(task["id"])
    assert result["status"] == "succeeded"
    assert result["repairAttempts"] == 3
    assert result["validation"]["valid"] is True
    narrative = repository.load_artifact(task["id"], StoryGenerationStage.NARRATIVE)
    assert narrative["nodes"][0]["title"] == "Still broken"
    assert "ghost" not in narrative["nodes"][2]["castPolicy"]["required"]
    assert repository.load_draft(task["id"]) is not None

    model.calls.clear()
    resumed = service.run(task["id"], resume=True)
    assert resumed["status"] == "succeeded"
    assert "repair" not in model.calls
    assert (
        repository.load_artifact(task["id"], StoryGenerationStage.NARRATIVE)["nodes"][0][
            "title"
        ]
        == "Still broken"
    )


def test_applied_repair_survives_downstream_regeneration(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"][2]["castPolicy"]["required"] = ["ghost"]
    model = RepairingModel(artifacts)
    service, repository = service_at(tmp_path, model)
    task = service.create("Keep repaired narrative.", task_id="repair-keep")
    result = service.run(task["id"])
    assert result["status"] == "succeeded"

    repaired = repository.load_artifact(task["id"], StoryGenerationStage.NARRATIVE)
    assert repaired["nodes"][2]["castPolicy"]["required"] == ["ling"]
    reset = service.regenerate_from(task["id"], StoryGenerationStage.LOGIC)
    assert reset["status"] == "queued"
    kept = repository.load_artifact(task["id"], StoryGenerationStage.NARRATIVE)
    assert kept["nodes"][2]["castPolicy"]["required"] == ["ling"]


def test_resource_bindings_are_retained_after_parse(tmp_path: Path) -> None:
    artifacts = stage_artifacts()
    artifacts["resources"]["bindings"] = {"openingBackground": "school-yard"}
    model = ScriptedModel(artifacts)
    service, _ = service_at(tmp_path, model)
    task = service.create(
        "Bind opening background.",
        task_id="binding-task",
        resource_catalog={"backgrounds": [{"id": "school-yard"}]},
    )
    result = service.run(task["id"])
    source = json.loads(Path(result["draftPath"]).read_text(encoding="utf-8"))
    project = parse_story_project(source)
    assert project.metadata.resource_bindings["openingBackground"] == "school-yard"

    state = SimpleNamespace(
        chat_session={},
        config_manager=SimpleNamespace(
            get_background_by_name=lambda name: SimpleNamespace(
                sprites=[SimpleNamespace(path=f"media/{name}.png")]
            )
        ),
    )
    patch = apply_story_resource_bindings(state, project.metadata.resource_bindings)
    assert state.chat_session["backgroundName"] == "school-yard"
    assert patch["backgroundPath"] == "media/school-yard.png"


def test_background_failure_writes_generation_task_snapshot(tmp_path: Path) -> None:
    model = ScriptedModel(stage_artifacts(), fail_once_at="bible")
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

    with pytest.raises(RuntimeError, match="transient"):
        run_story_generation_background(state, bridge["id"], generated["id"])
    updated = _get_task(state, bridge["id"])
    assert updated["generationTask"]["status"] == "failed"
    assert updated["generationTask"]["currentStage"] == "bible"


def test_validator_detects_secret_in_title_and_choice_label() -> None:
    source = campus_mystery_source()
    source["narrativeGraph"]["nodes"][0]["title"] = "The key is a replica"
    source["narrativeGraph"]["nodes"][0]["choices"][0]["label"] = (
        "The key is a replica"
    )
    report = StoryDraftValidator().validate(
        source, story_bible={"secrets": ["The key is a replica"]}
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
        if generated.get("completedStages") == ["requirements"]:
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
    assert report["generationCost"]["requests"] == 4
    assert report["generationCost"]["estimatedTokens"] > 0
