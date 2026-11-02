"""Durable, single-owner automatic recovery for the story compiler.

An authoring pass is bounded; the job is not. Failed passes feed their diagnostics
back to the author, with stage rewrites when patches stop making progress. Only a
validated draft, explicit cancellation, or host shutdown ends the worker.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import logging
import threading
import time
from typing import Any

from config.feature_flags import FeatureFlag
from core.story import canonical_json
from application.story.generation import (
    GENERATION_STAGES,
    MAX_REPAIR_ATTEMPTS,
    StoryGenerationCancelled,
    StoryGenerationError,
    StoryGenerationService,
    StoryGenerationStage,
)

logger = logging.getLogger(__name__)
_controllers_lock = threading.Lock()


class StoryGenerationRecovery:
    def __init__(
        self, service: StoryGenerationService, *, retry_seconds: float = 2
    ) -> None:
        self.service = service
        self.retry_seconds = retry_seconds
        self._guard = threading.Lock()
        self._jobs: dict[str, threading.Event] = {}
        self._errors: dict[str, Exception] = {}
        self._shutdown = threading.Event()

    def ensure(self, task_id: str, *, resume: bool = False) -> dict[str, Any]:
        """Attach to an existing worker or start one; reads never revive cancellation."""
        with self._guard:
            task = self.service.get(task_id)
            active = self._jobs.get(task_id)
            if active is not None and not active.is_set():
                return task
            if task["status"] == "succeeded":
                return task
            if task.get("cancelRequested") or task["status"] == "cancelled":
                if not resume:
                    return task
                with self.service._lock_for(task_id):
                    task.update(cancelRequested=False, status="queued", error=None)
                    task = self.service.repository.save(task, preserve_cancel=False)
            self._errors.pop(task_id, None)
            done = threading.Event()
            self._jobs[task_id] = done
            task.update(status="running", error=None)
            task["recovery"] = {
                **(task.get("recovery") or {}),
                "state": "resuming",
                "message": "正在自动从已保存的进度继续",
            }
            task = self.service.repository.save(task)
            threading.Thread(
                target=self._work,
                args=(task_id, done),
                name=f"story-author-{task_id[:12]}",
                daemon=True,
            ).start()
            return task

    def recover_pending(self) -> None:
        for path in self.service.repository.root.glob("*/task.json"):
            if self._shutdown.is_set():
                break
            try:
                self.ensure(path.parent.name)
            except Exception:
                logger.exception(
                    "Could not recover story generation %s", path.parent.name
                )

    def stop(self) -> None:
        # Preserve durable progress; a new host will resume without a cancel flag.
        self._shutdown.set()

    def wait(
        self,
        task_id: str,
        *,
        resume: bool = False,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self.ensure(task_id, resume=resume)
        previous = None
        while True:
            if is_cancelled and is_cancelled():
                self.service.cancel(task_id)
            task = self.service.get(task_id)
            if task != previous:
                self.service._notify(on_progress, task, None)
                previous = task
            if task.get("cancelRequested") or task["status"] == "cancelled":
                raise StoryGenerationCancelled()
            if task["status"] == "succeeded":
                return task
            with self._guard:
                done = self._jobs.get(task_id)
                error = self._errors.get(task_id)
            if error:
                raise error
            if self._shutdown.wait(0.1) or (done is not None and done.is_set()):
                # Re-read once: the worker can finish between our snapshot and event.
                result = self.service.get(task_id)
                if result["status"] == "succeeded":
                    return result
                if result.get("cancelRequested"):
                    raise StoryGenerationCancelled()
                raise self._errors.get(task_id) or StoryGenerationError(
                    "generation.host_stopped", "后台已停止，重新启动后会自动继续"
                )

    def _work(self, task_id: str, done: threading.Event) -> None:
        try:
            with self.service._lock_for(task_id):
                self._verify_checkpoints(task_id)
            while not self._shutdown.is_set():
                self.service.flags.require(FeatureFlag.STORY_SYSTEM)
                task = self.service.get(task_id)
                if task.get("cancelRequested") or task["status"] == "cancelled":
                    return
                # Keep the saved retry deadline across host restarts.
                deadline = ((task.get("recovery") or {}).get("nextRetryAt") or 0) / 1000
                while time.time() < deadline:
                    if self._shutdown.wait(max(0, min(0.2, deadline - time.time()))):
                        return
                    if self.service.get(task_id).get("cancelRequested"):
                        return
                task["recovery"] = {
                    **(task.get("recovery") or {}),
                    "state": "working",
                    "nextRetryAt": None,
                    "message": "正在生成并自动检查剧本",
                }
                self.service.repository.save(task)
                try:
                    self.service.run(task_id)
                    return
                except StoryGenerationCancelled:
                    return
                except OSError:
                    # Storage failures cannot be corrected by spending more model calls.
                    raise
                except Exception as error:
                    if getattr(error, "code", "") == "generation.already_running":
                        if self._shutdown.wait(0.2):
                            return
                        continue
                    self._schedule_retry(task_id, error)
        except Exception as error:
            with self._guard:
                self._errors[task_id] = error
            logger.exception("Story generation recovery stopped: %s", task_id)
        finally:
            done.set()

    def _schedule_retry(self, task_id: str, error: Exception) -> None:
        with self.service._lock_for(task_id):
            task = self.service.repository.load(task_id)
            if task.get("cancelRequested"):
                return
            recovery = task.get("recovery") or {}
            attempt = int(recovery.get("attempt", 0)) + 1
            patch_failures = int(recovery.get("patchFailures", 0))
            code = str(getattr(error, "code", "generation.stage_failed"))
            author_error = isinstance(error, StoryGenerationError) and code not in {
                "generation.model_not_configured",
                "generation.model_request_failed",
                "generation.stage_failed",
            }
            if task.get("currentStage") == "repair" and author_error:
                patch_failures += 1
            rewrite = (
                code == "generation.validation_failed"
                or patch_failures >= MAX_REPAIR_ATTEMPTS
            )
            if rewrite:
                issues = (task.get("validation") or {}).get("issues", [])
                stage = StoryGenerationStage.NARRATIVE
                if any(
                    str(issue.get("path", "")).startswith("/cast") for issue in issues
                ):
                    stage = StoryGenerationStage.CHARACTERS
                self._rewind(task, stage)
                patch_failures = 0
            delay = (
                self.retry_seconds
                if author_error
                else min(60, self.retry_seconds * 2 ** min(attempt - 1, 5))
            )
            if code == "generation.model_not_configured":
                delay = max(delay, 30)
            message = (
                "局部修复未通过，正在自动重写出错阶段"
                if rewrite
                else "生成内容未通过检查，正在让 LLM 根据错误自动修复"
                if author_error
                else "模型调用暂时不可用，将自动重试并从断点继续"
            )
            task.update(status="running", error=None)
            task["recovery"] = {
                "state": "correcting" if author_error else "waiting",
                "attempt": attempt,
                "patchFailures": patch_failures,
                "message": message,
                "nextRetryAt": int((time.time() + delay) * 1000),
                "lastError": {"code": code, "message": str(error)},
            }
            self.service.repository.save(task)

    def _rewind(self, task: dict[str, Any], stage: StoryGenerationStage) -> None:
        kept = {
            item.value for item in GENERATION_STAGES[: GENERATION_STAGES.index(stage)]
        }
        task["completedStages"] = [
            item for item in task.get("completedStages", []) if item in kept
        ]
        task["artifactHashes"] = {
            key: value
            for key, value in task.get("artifactHashes", {}).items()
            if key in kept
        }
        task.update(currentStage=stage.value, draftPath="")
        # Persist invalidation before deleting files so a crash cannot reuse them.
        self.service.repository.save(task)
        self.service.repository.delete_artifacts_from(task["id"], stage)

    def _verify_checkpoints(self, task_id: str) -> None:
        task = self.service.repository.load(task_id)
        for stage in GENERATION_STAGES:
            if stage.value not in task.get("completedStages", []):
                # A crash while checkpointing may leave an uncommitted draft.
                self._rewind(task, stage)
                return
            try:
                artifact = self.service.repository.load_artifact(task_id, stage)
                digest = hashlib.sha256(
                    canonical_json(artifact).encode("utf-8")
                ).hexdigest()
                if digest != task.get("artifactHashes", {}).get(stage.value):
                    raise StoryGenerationError(
                        "generation.checkpoint_invalid",
                        f"{stage.value} checkpoint hash mismatch",
                    )
            except StoryGenerationError as error:
                task["recoveryContext"] = {
                    "error": {"code": error.code, "message": str(error)}
                }
                self._rewind(task, stage)
                return
        try:
            draft = self.service.repository.load_draft(task_id)
            if draft is None:
                return
            folded = self.service._artifacts_from_source(task_id, draft)
            if all(
                hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
                == task["artifactHashes"][stage.value]
                for stage, value in folded.items()
            ):
                return
        except (StoryGenerationError, TypeError, ValueError):
            pass
        # Artifacts are authoritative; discard only an incomplete/stale draft.
        (self.service.repository.task_directory(task_id) / "draft.json").unlink(
            missing_ok=True
        )


def recovery_for(service: StoryGenerationService) -> StoryGenerationRecovery:
    with _controllers_lock:
        recovery = getattr(service, "_recovery", None)
        if recovery is None:
            recovery = StoryGenerationRecovery(service)
            service._recovery = recovery
        return recovery


def recover_story_generations(state: Any) -> None:
    if not state.config_manager.feature_flags.is_enabled(FeatureFlag.STORY_SYSTEM):
        return
    from application.story.generation import story_generation_service_for_state

    recovery_for(story_generation_service_for_state(state)).recover_pending()
