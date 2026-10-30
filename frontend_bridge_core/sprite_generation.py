"""Task and persistence boundary for the character sprite generator."""

from pathlib import Path
from types import SimpleNamespace

from application.characters.generate_sprites import (
    plan_sprites,
    prompt_pair,
    render_sprite,
    capture_sprite_frame,
    remove_sprite_background,
)
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
from application.characters.animate_sprites import (
    animation_prompt,
    render_animation,
    make_transparent_animation,
    verify_transparent_animation,
)
from frontend_bridge_core.tools import _local_file_access_roots
from sdk.path_utils import safe_existing_file_path


def run_sprite_plan(state, task_id, payload):
    _update_task(
        state,
        task_id,
        message="正在根据人物性格设计提示词和标签。",
        phase="prompt",
        progress=0.1,
    )
    return plan_sprites(state.config_manager, payload)


def run_sprite_animation(state, task_id, payload):
    animation_prompt(payload)
    name = str(payload.get("name") or "").strip()
    if not state.config_manager.get_character_by_name(name):
        raise ValueError("请先保存角色再生成动态立绘")
    if not payload.get("referenceImage"):
        raise ValueError("请先选择静态参考立绘")
    from PIL import Image

    reference = safe_existing_file_path(
        str(payload["referenceImage"]),
        roots=_local_file_access_roots(state),
        field="referenceImage",
    )
    with Image.open(reference) as image:
        image.verify()
    output = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{task_id}.png"
    )
    _update_task(
        state,
        task_id,
        message="正在用 H3 生成固定镜头的轻微动态。",
        phase="generate",
        progress=0.1,
    )
    result = render_animation(
        state.config_manager, {**payload, "name": name}, output, reference
    )
    return _finish_animation(state, task_id, result)


def _finish_animation(state, task_id, source):

    video = safe_existing_file_path(
        source["videoPath"],
        roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
        field="generatedVideo",
    )
    output = video.parent / f"{task_id}-alpha.webm"
    result = {
        **source,
        "taskId": task_id,
        "animation": True,
        "alphaVerified": False,
        "path": video.as_posix(),
        "backgroundRemoved": False,
    }
    result.pop("backgroundRemovalError", None)

    def progress(done, total):
        if done == 1 or done % 4 == 0 or done == total:
            _update_task(
                state,
                task_id,
                phase="video-matting",
                progress=0.55 + 0.4 * min(done / total, 1),
                message=f"正在逐帧抠图并编码透明视频：{done}/{total}",
            )

    _update_task(
        state,
        task_id,
        phase="video-matting",
        progress=0.55,
        message="正在逐帧移除背景，完成后将校验真实 Alpha 通道。",
    )
    try:
        metadata = make_transparent_animation(
            video,
            output,
            progress=progress,
            playback_speed=source.get("playbackSpeed", 0.75),
        )
        result.update(metadata, path=output.as_posix(), backgroundRemoved=True)
    except Exception as exc:
        result["backgroundRemovalError"] = str(exc)
    return _approve_sprite_media(state, result)


def run_sprite_render(state, task_id, payload):
    remove_background = _auto_remove_background(payload)
    name = str(payload.get("name") or "").strip()
    if not state.config_manager.get_character_by_name(name):
        raise ValueError("请先保存角色再生成立绘")
    reference = None
    if payload.get("referenceImage"):
        from PIL import Image

        reference = safe_existing_file_path(
            str(payload["referenceImage"]),
            roots=_local_file_access_roots(state),
            field="referenceImage",
        )
        with Image.open(reference) as image:
            image.verify()
    output = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{task_id}.png"
    )
    _update_task(
        state,
        task_id,
        message="正在生成立绘，耗时取决于模型和工作流。",
        phase="generate",
        progress=0.15,
    )
    result = render_sprite(
        state.config_manager, {**payload, "name": name}, output, reference
    )
    return _finish_sprite(state, task_id, result, remove_background)


def _auto_remove_background(payload):
    enabled = payload.get("removeBackground", True)
    if not isinstance(enabled, bool):
        raise ValueError("removeBackground 必须为布尔值")
    return enabled


def _finish_sprite(state, task_id, result, remove_background):
    result = {**result, "taskId": task_id, "backgroundRemoved": False}
    if not remove_background:
        return _approve_sprite_media(state, result)
    _update_task(
        state,
        task_id,
        phase="remove-background",
        message="正在自动移除立绘背景。",
        progress=0.8,
    )
    original = Path(result["path"])
    output = original.with_name(f"{task_id}-cutout.png")
    try:
        result = {
            **remove_sprite_background(result, original, output),
            "taskId": task_id,
        }
    except Exception as exc:
        # A successful, expensive render stays usable even if local matting fails.
        result = {**result, "backgroundRemovalError": str(exc)}
    return _approve_sprite_media(state, result)


def _approve_sprite_media(state, result):
    approve = getattr(
        getattr(state, "chat_stream", None), "approve_external_media_path", None
    )
    if callable(approve):
        for key in ("path", "originalPath", "videoPath"):
            if result.get(key):
                path = safe_existing_file_path(
                    result[key],
                    roots=(
                        Path(state.project_root_dir) / "cache" / "sprite_generation",
                    ),
                    field="generatedMedia",
                )
                approve(path.as_posix())
    return result


def _generated_task(state, task_id, name):
    task = state.tasks.get(task_id)
    if (
        not task
        or task["kind"]
        not in {
            "character-sprite-render",
            "character-sprite-frame",
            "character-sprite-cutout",
            "character-sprite-animate",
        }
        or task["status"] != "succeeded"
    ):
        raise ValueError("立绘结果不可用，请重新生成")
    if (task.get("result") or {}).get("name") != name:
        raise ValueError("立绘结果不属于当前角色")
    return task


def run_sprite_frame(state, task_id, payload):
    remove_background = _auto_remove_background(payload)
    name = str(payload.get("name") or "").strip()
    with state.task_lock:
        source = dict(
            _generated_task(state, str(payload.get("taskId") or ""), name)["result"]
        )
    if not source.get("videoPath"):
        raise ValueError("这张立绘没有可截帧的视频")
    video = safe_existing_file_path(
        source["videoPath"],
        roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
        field="generatedVideo",
    )
    if payload.get("seconds") is None:
        raise ValueError("请选择截帧时间")
    output = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{task_id}.png"
    )
    _update_task(
        state, task_id, phase="frame", message="正在截取选中的视频画面。", progress=0.3
    )
    result = capture_sprite_frame(source, video, output, payload["seconds"])
    return _finish_sprite(state, task_id, result, remove_background)


def run_sprite_cutout(state, task_id, payload):
    name = str(payload.get("name") or "").strip()
    with state.task_lock:
        source = dict(
            _generated_task(state, str(payload.get("taskId") or ""), name)["result"]
        )
    if source.get("animation"):
        return _finish_animation(state, task_id, source)
    original = safe_existing_file_path(
        source.get("originalPath") or source["path"],
        roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
        field="generatedImage",
    )
    output = original.parent / f"{task_id}-cutout.png"
    _update_task(
        state,
        task_id,
        phase="remove-background",
        message="正在移除立绘背景。",
        progress=0.3,
    )
    return _approve_sprite_media(
        state, {**remove_sprite_background(source, original, output), "taskId": task_id}
    )


def import_generated_sprites(state, payload):
    name = str(payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError("请选择 1–12 张生成的立绘")
    replacement = payload.get("replace")
    if replacement is not None and (
        not isinstance(replacement, dict)
        or len(items) != 1
        or isinstance(replacement.get("index"), bool)
        or not isinstance(replacement.get("index"), int)
        or not isinstance(replacement.get("path"), str)
    ):
        raise ValueError("替换时请选择一张结果和有效的原立绘")
    # Serialize imports and mark task results together, making repeated submissions idempotent.
    with state.task_lock:
        character = state.config_manager.get_character_by_name(name)
        if character is None:
            raise ValueError("找不到角色，请先保存角色")
        tasks, tags, files, seen = [], [], [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("无效的立绘结果")
            task_id = str(item.get("taskId") or "")
            if task_id in seen:
                continue
            seen.add(task_id)
            task = _generated_task(state, task_id, name)
            result = task.get("result") or {}
            if result.get("imported"):
                continue
            path = safe_existing_file_path(
                result["path"],
                roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
                field="generatedImage",
            )
            if result.get("animation"):
                if not result.get("alphaVerified") or path.suffix.lower() != ".webm":
                    raise ValueError("动态立绘尚未完成透明处理，请先重试逐帧抠图")
                verify_transparent_animation(path)
            pair = prompt_pair(
                {
                    "prompt": result["prompt"],
                    "tagging": item.get("tagging", result["tagging"]),
                }
            )
            tasks.append(task)
            files.append(SimpleNamespace(name=str(path)))
            tags.append(pair["tagging"])
        if files:
            state.character_manager.upload_sprites(
                name,
                files,
                character.emotion_tags,
                sprite_tags=tags,
                **(
                    {
                        "replace_index": replacement["index"],
                        "expected_path": replacement["path"],
                    }
                    if replacement is not None
                    else {}
                ),
            )
            for task in tasks:
                task["result"] = {**task["result"], "imported": True}
    state.config_manager.reload()
    return _jsonify(state.config_manager.get_character_by_name(name))
