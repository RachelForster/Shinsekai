from __future__ import annotations

from application.chat.runtime_process import _chat_snapshot
from application.story.coordinator import (
    publish_story_transition,
    start_or_recover_story_session,
    story_snapshot_patch,
)
from application.story.generation import (
    StoryGenerationStage,
    run_story_generation_background,
    story_generation_service_for_state,
)
from application.story.generation_recovery import recovery_for
from application.story.generation_preview import generation_preview
from application.story.selection import generation_selection
from application.story.library import list_story_library, prepare_story_launch
from frontend_bridge_core.chat_session import (
    _generate_system_template_for_mode,
    _usable_media_selection_mode,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)
from sdk.logging import new_log_id


def _prepare_launch(request: ApiRequest) -> JsonResponse:
    payload = prepare_story_launch(
        request.state,
        str(request.body.get("storyPath") or ""),
        str(request.body.get("historyPath") or ""),
    )
    payload["mediaSelectionMode"] = _usable_media_selection_mode(
        payload.get("mediaSelectionMode")
    )
    payload["system"] = _generate_system_template_for_mode(
        request.state,
        characters=payload["characters"],
        background=payload["backgroundName"],
        source=payload,
        media_selection_mode=payload["mediaSelectionMode"],
    )
    return JsonResponse(payload)


def _generation_preview(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        generation_preview(
            story_generation_service_for_state(request.state),
            request.params["generation_task_id"],
        )
    )


def _get_generation(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        recovery_for(story_generation_service_for_state(request.state)).ensure(
            request.params["generation_task_id"]
        )
    )


def _start_story(request: ApiRequest) -> JsonResponse:
    story_path = str(request.body.get("storyPath") or "").strip()
    if not story_path:
        raise ValueError("storyPath is required")
    start_or_recover_story_session(
        request.state,
        story_path,
        command_id=str(request.body.get("commandId") or new_log_id()),
    )
    patch = story_snapshot_patch(request.state)
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
    options = (
        request.body.get("options")
        if isinstance(request.body.get("options"), dict)
        else {}
    )
    resource_catalog = (
        request.body.get("resourceCatalog")
        if isinstance(request.body.get("resourceCatalog"), dict)
        else {}
    )
    synopsis = str(request.body.get("synopsis") or "").strip()
    if "characters" in options:
        options, resource_catalog = generation_selection(request.state, options)
        synopsis = (
            synopsis
            or f"围绕人物{'、'.join(options['characters'])}，在{options['backgroundName']}展开一个有起承转合的互动故事。"
        )
    generation_task = story_generation_service_for_state(request.state).create(
        synopsis,
        options=options,
        resource_catalog=resource_catalog,
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
        pattern="/api/story/library",
        handler=lambda request: JsonResponse(list_story_library(request.state)),
        body_kind=BodyKind.NONE,
        name="story.library",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/story/launch-payload",
        handler=_prepare_launch,
        name="story.launch-payload",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/story/generation/{generation_task_id}/preview",
        handler=_generation_preview,
        body_kind=BodyKind.NONE,
        name="story.generation.preview",
    ),
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
