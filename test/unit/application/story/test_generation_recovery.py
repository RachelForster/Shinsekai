from copy import deepcopy
import threading
import time

import pytest

from application.story.generation import (
    StoryGenerationError,
    StoryGenerationCancelled,
    _parse_json_mapping,
)
from application.story.generation_recovery import StoryGenerationRecovery
from test.unit.application.story.test_generation import (
    ScriptedModel,
    NoOpRepairModel,
    RepairingModel,
    service_at,
    stage_artifacts,
)


@pytest.fixture
def recovery_factory():
    controllers = []
    timers = []

    def create(service, *, delay=0):
        controller = StoryGenerationRecovery(service, retry_seconds=delay)
        controllers.append(controller)
        timer = threading.Timer(8, controller.stop)
        timer.daemon = True
        timer.start()
        timers.append(timer)
        return controller

    yield create
    for controller in controllers:
        controller.stop()
        for event in controller._jobs.values():
            event.wait(2)
    for timer in timers:
        timer.cancel()


def wait_for(predicate):
    deadline = time.monotonic() + 4
    while not predicate():
        assert time.monotonic() < deadline, "recovery did not reach expected state"
        time.sleep(0.01)


def test_automatic_retry_preserves_successful_stages_and_counts_failed_calls(
    tmp_path, recovery_factory
):
    model = ScriptedModel(stage_artifacts(), fail_once_at="narrative")
    service, _ = service_at(tmp_path, model)
    task = service.create("Resume the failed stage")
    result = recovery_factory(service).wait(task["id"])
    assert result["status"] == "succeeded"
    assert result["validation"]["valid"]
    assert result["cost"]["requests"] == 4
    assert model.calls == ["foundation", "characters", "narrative", "narrative"]
    assert (
        model.requests[-1]["correctionFeedback"]["error"]["message"]
        == "transient model failure"
    )


def test_invalid_json_and_schema_are_returned_to_author_for_correction(
    tmp_path, recovery_factory
):
    class BadThenGood(ScriptedModel):
        attempts = 0

        def complete(self, request):
            if request.get("stage") == "foundation":
                self.attempts += 1
                if self.attempts == 1:
                    return _parse_json_mapping('{"title":')
                feedback = request["correctionFeedback"]
                if self.attempts == 2:
                    assert feedback["rejectedOutput"] == '{"title":'
                    assert "invalid JSON" in feedback["error"]["message"]
                    return {"artifact": {"id": "bad"}}
                assert "title" in feedback["error"]["message"]
                assert '"id": "bad"' in feedback["rejectedOutput"]
            return super().complete(request)

    model = BadThenGood(stage_artifacts())
    service, _ = service_at(tmp_path, model)
    result = recovery_factory(service).wait(
        service.create("Correct invalid author JSON")["id"]
    )
    assert result["status"] == "succeeded"
    assert result["cost"]["requests"] == 5


def test_repair_receives_diagnostics_and_recovers_invalid_patch(
    tmp_path, recovery_factory
):
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"].append(
        {"id": "orphan-ending", "title": "Orphan", "type": "ending_node"}
    )

    class BadPatchThenGood(RepairingModel):
        patches = 0

        def complete(self, request):
            if request["operation"] == "repair":
                self.patches += 1
                assert request["validationIssues"]
                if self.patches == 1:
                    return {"baseVersion": 999, "operations": []}
                assert request["correctionFeedback"]["error"]["code"].startswith(
                    "generation.patch"
                )
            return super().complete(request)

    model = BadPatchThenGood(artifacts)
    service, _ = service_at(tmp_path, model)
    result = recovery_factory(service).wait(service.create("Repair graph")["id"])
    assert result["validation"]["valid"]
    assert result["repairAttempts"] == 2
    assert result["cost"]["requests"] == 5


def test_exhausted_patch_pass_rewrites_narrative_until_playable(
    tmp_path, recovery_factory
):
    artifacts = stage_artifacts()
    artifacts["narrative"]["nodes"].append(
        {"id": "orphan-ending", "title": "Orphan", "type": "ending_node"}
    )

    class RewriteAfterNoOps(NoOpRepairModel):
        narratives = 0

        def complete(self, request):
            if request.get("stage") == "narrative":
                self.narratives += 1
                if self.narratives == 2:
                    assert request["correctionFeedback"]["validationIssues"]
                    self.artifacts["narrative"] = deepcopy(
                        stage_artifacts()["narrative"]
                    )
            return super().complete(request)

    model = RewriteAfterNoOps(artifacts)
    service, _ = service_at(tmp_path, model)
    result = recovery_factory(service).wait(
        service.create("Rewrite when patching stalls")["id"]
    )
    assert result["status"] == "succeeded"
    assert result["repairAttempts"] == 3
    assert model.calls.count("foundation") == model.calls.count("characters") == 1
    assert model.calls.count("narrative") == 2


def test_host_restart_recovers_disk_checkpoints_without_frontend_request(
    tmp_path, recovery_factory
):
    original, _ = service_at(
        tmp_path, ScriptedModel(stage_artifacts(), fail_once_at="characters")
    )
    task = original.create("Restart the host")
    with pytest.raises(RuntimeError):
        original.run(task["id"])
    model = ScriptedModel(stage_artifacts())
    restarted, _ = service_at(tmp_path, model)
    controller = recovery_factory(restarted)
    controller.recover_pending()
    wait_for(lambda: restarted.get(task["id"])["status"] == "succeeded")
    assert model.calls == ["characters", "narrative"]


def test_recovery_rebuilds_corrupt_checkpoint_and_downstream_only(
    tmp_path, recovery_factory
):
    service, repository = service_at(
        tmp_path, ScriptedModel(stage_artifacts(), fail_once_at="narrative")
    )
    task = service.create("Recover corrupt characters")
    with pytest.raises(RuntimeError):
        service.run(task["id"])
    (
        repository.task_directory(task["id"]) / "artifacts" / "characters.json"
    ).write_text("{}", encoding="utf-8")
    service.model = ScriptedModel(stage_artifacts())
    result = recovery_factory(service).wait(task["id"])
    assert result["validation"]["valid"]
    assert service.model.calls == ["characters", "narrative"]


def test_duplicate_reads_share_worker_and_cancellation_is_not_resurrected(
    tmp_path, recovery_factory
):
    entered = threading.Event()
    release = threading.Event()

    class BlockingModel(ScriptedModel):
        def complete(self, request):
            entered.set()
            assert release.wait(4)
            return super().complete(request)

    model = BlockingModel(stage_artifacts())
    service, _ = service_at(tmp_path, model)
    task = service.create("Only one author")
    controller = recovery_factory(service)
    controller.ensure(task["id"])
    assert entered.wait(3)
    for _ in range(5):
        controller.ensure(task["id"])
    service.cancel(task["id"])
    release.set()
    assert controller._jobs[task["id"]].wait(3)
    controller.recover_pending()
    assert controller.ensure(task["id"])["status"] == "cancelled"
    assert model.calls == ["foundation"]
    assert service.get(task["id"])["completedStages"] == []


def test_cancel_during_backoff_stops_further_model_calls(tmp_path, recovery_factory):
    model = ScriptedModel(stage_artifacts(), fail_once_at="foundation")
    service, _ = service_at(tmp_path, model)
    task = service.create("Cancel retry")
    controller = recovery_factory(service, delay=30)
    controller.ensure(task["id"])
    wait_for(
        lambda: (service.get(task["id"]).get("recovery") or {}).get("state")
        == "waiting"
    )
    service.cancel(task["id"])
    with pytest.raises(StoryGenerationCancelled):
        controller.wait(task["id"])
    assert controller._jobs[task["id"]].wait(3)
    assert model.calls == ["foundation"]


def test_more_than_three_bad_stage_outputs_still_eventually_succeed(
    tmp_path, recovery_factory
):
    class RepeatedErrors(ScriptedModel):
        failures = 0

        def complete(self, request):
            if self.failures < 5:
                self.failures += 1
                raise StoryGenerationError(
                    "generation.model_json_invalid", "broken JSON"
                )
            return super().complete(request)

    model = RepeatedErrors(stage_artifacts())
    service, _ = service_at(tmp_path, model)
    result = recovery_factory(service).wait(
        service.create("Keep correcting until valid")["id"]
    )
    assert result["status"] == "succeeded"
    assert result["cost"]["requests"] == 8


def test_network_timeout_is_retried_instead_of_treated_as_disk_failure(
    tmp_path, recovery_factory
):
    class TimeoutOnce(ScriptedModel):
        timed_out = False

        def complete(self, request):
            if not self.timed_out:
                self.timed_out = True
                raise TimeoutError("model request timed out")
            return super().complete(request)

    service, _ = service_at(tmp_path, TimeoutOnce(stage_artifacts()))
    result = recovery_factory(service).wait(
        service.create("Retry network timeout")["id"]
    )
    assert result["status"] == "succeeded"
    assert result["cost"]["requests"] == 4
