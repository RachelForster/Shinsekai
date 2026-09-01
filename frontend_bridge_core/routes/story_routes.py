from __future__ import annotations

from application.chat.runtime_process import _chat_snapshot
from application.story.coordinator import (
    publish_story_transition,
    start_or_recover_story_session,
)
from application.story.generation import (
    StoryGenerationStage,
    run_story_generation_background,
    story_generation_service_for_state,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)
from sdk.logging import new_log_id


def _get_generation(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        story_generation_service_for_state(request.state).get(
            request.params["generation_task_id"]
        )
    )


def _start_story(request: ApiRequest) -> JsonResponse:
    story_path = str(request.body.get("storyPath") or "").strip()
    if not story_path:
        raise ValueError("storyPath is required")
    session = start_or_recover_story_session(
        request.state,
        story_path,
        command_id=str(request.body.get("commandId") or new_log_id()),
    )
    patch = session.chat_snapshot()
    publish_story_transition(request.state, patch)
    return JsonResponse(_chat_snapshot(request.state, "idle", extra=patch))


def _generation_task_response(
    request: ApiRequest,
    generation_task: dict,
    *,
    title: str,
    message: str,
    resume: bool = False,
    generation_task_id: str = "",
) -> TaskResponse:
    selected_task_id = generation_task_id or str(generation_task["id"])
    return TaskResponse(
        kind="story-generation",
        title=title,
        message=message,
        task_updates={
            "generationTaskId": selected_task_id,
            "generationTask": generation_task,
        },
        worker=lambda task_id: run_story_generation_background(
            request.state,
            task_id,
            selected_task_id,
            resume=resume,
        ),
    )


def _start_generation(request: ApiRequest) -> TaskResponse:
    generation_task = story_generation_service_for_state(request.state).create(
        str(request.body.get("synopsis") or ""),
        options=(
            request.body.get("options")
            if isinstance(request.body.get("options"), dict)
            else {}
        ),
        resource_catalog=(
            request.body.get("resourceCatalog")
            if isinstance(request.body.get("resourceCatalog"), dict)
            else {}
        ),
    )
    return _generation_task_response(
        request,
        generation_task,
        title="AI story compiler",
        message="Story generation queued.",
    )


def _resume_generation(request: ApiRequest) -> TaskResponse:
    generation_task_id = request.params["generation_task_id"]
    generation_task = story_generation_service_for_state(request.state).get(
        generation_task_id
    )
    return _generation_task_response(
        request,
        generation_task,
        title="Resume AI story compiler",
        message="Story generation resume queued.",
        resume=True,
        generation_task_id=generation_task_id,
    )


def _regenerate_generation(request: ApiRequest) -> TaskResponse:
    generation_task_id = request.params["generation_task_id"]
    generation_task = story_generation_service_for_state(request.state).regenerate_from(
        generation_task_id,
        StoryGenerationStage(str(request.body.get("stage") or "")),
    )
    return _generation_task_response(
        request,
        generation_task,
        title="Regenerate story stage",
        message="Partial story regeneration queued.",
        generation_task_id=generation_task_id,
    )


def _cancel_generation(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        story_generation_service_for_state(request.state).cancel(
            request.params["generation_task_id"]
        )
    )


STORY_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/story/generation/{generation_task_id}",
        handler=_get_generation,
        body_kind=BodyKind.NONE,
        name="story.generation.get",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/story/start",
        handler=_start_story,
        name="story.start",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/story/generation/start",
        handler=_start_generation,
        name="story.generation.start",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/story/generation/{generation_task_id}/resume",
        handler=_resume_generation,
        name="story.generation.resume",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/story/generation/{generation_task_id}/regenerate",
        handler=_regenerate_generation,
        name="story.generation.regenerate",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/story/generation/{generation_task_id}/cancel",
        handler=_cancel_generation,
        name="story.generation.cancel",
    ),
)
