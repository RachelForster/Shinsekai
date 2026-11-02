"""Read generation checkpoints for the authoring UI without exposing file access."""

from __future__ import annotations

from typing import Any

from .generation import GENERATION_STAGES, StoryGenerationService


def generation_preview(service: StoryGenerationService, task_id: str) -> dict[str, Any]:
    # Regeneration removes checkpoints under this same task lock. A preview must
    # never read the old manifest halfway through that removal.
    with service._lock_for(task_id):
        return _read_preview(service, task_id)


def _read_preview(service: StoryGenerationService, task_id: str) -> dict[str, Any]:
    task = service.get(task_id)
    artifacts = {
        stage.value: service.repository.load_artifact(task_id, stage)
        for stage in GENERATION_STAGES
        if stage.value in task["completedStages"]
    }
    # A repaired draft is authoritative. Earlier checkpoints can still be viewed
    # while generation is running, but must not replace the final graph.
    complete = all(
        stage.value in task["completedStages"] for stage in GENERATION_STAGES
    )
    draft = service.repository.load_draft(task_id) if complete else None
    if draft and any(
        artifact != artifacts.get(stage.value)
        for stage, artifact in service._artifacts_from_source(task_id, draft).items()
    ):
        draft = None
    narrative = (draft or {}).get("narrativeGraph") or artifacts.get("narrative")
    return {
        "artifacts": artifacts,
        "graph": narrative,
        "title": (draft or artifacts.get("foundation", {})).get("title", ""),
    }
