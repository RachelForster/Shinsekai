"""Generate a short, locked-camera transition with two exact keyframes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from application.characters.sprite.animate_sprites import (
    _finish_animation,
    retry_animation_matting,
    verify_transparent_animation,
)
from application.characters.sprite.generate_sprites import (
    SPRITE_CAMERA_SUFFIX,
    SPRITE_REFERENCE_FRAMING_SUFFIX,
    _local_file_access_roots,
    _resolve_file_access_roots,
    boundary_frame,
    matting_options,
    render_sprite,
)
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
from core.sprite.selection import sprite_entry_path
from core.sprite.transitions import (
    TRANSITION_FRAME_COUNT,
    field,
    sprite_fingerprint,
    valid_transitions,
)
from sdk.path_utils import safe_existing_file_path

TRANSITION_PROMPT = (
    "make the character transition directly from the standing pose, hand positions "
    "and facial expression in the first reference to those in the last reference; "
    "begin changing pose immediately and progress continuously throughout the shot; "
    "complete the pose change and reach the last reference's hand positions and "
    "facial expression by the final frame; keep the feet planted, the original neck "
    "length and character proportions, and the same standing location; let the hair "
    "roots follow the head and torso motion, with the hair lengths and tips trailing "
    "slightly behind through natural inertia and coordinated follow-through, then "
    "settling toward the last reference pose while preserving the original hairstyle"
    + SPRITE_REFERENCE_FRAMING_SUFFIX
    + SPRITE_CAMERA_SUFFIX
)


def transition_identity(character, start, end):
    paths = {sprite_entry_path(sprite) for sprite in character.sprites}
    if (
        not isinstance(start, str)
        or not isinstance(end, str)
        or start == end
        or start not in paths
        or end not in paths
    ):
        raise ValueError("请选择角色立绘库中两张不同的立绘")
    return {
        "name": character.name,
        "fromPath": start,
        "toPath": end,
        "fromFingerprint": sprite_fingerprint(start),
        "toFingerprint": sprite_fingerprint(end),
    }


def saved_transitions(character):
    return [
        {
            "fromPath": field(edge, "from_path"),
            "toPath": field(edge, "to_path"),
            "path": field(edge, "path"),
            "frameCount": field(edge, "frame_count", 5),
        }
        for edge in valid_transitions(character)
    ]


def render_transition(config_store, payload, output, first, last):
    result = render_sprite(
        config_store,
        {**payload, "prompt": TRANSITION_PROMPT, "tagging": "过渡，站立"},
        output,
        first,
        require_h3_video=True,
        last_reference=last,
    )
    return {
        **result,
        "animation": True,
        "playbackSpeed": 1.0,
        "requestedFrames": TRANSITION_FRAME_COUNT,
    }


def _endpoints(
    state: Any, payload: dict, *, file_access_roots: Iterable[Path] = ()
):
    name = str(payload.get("name") or "").strip()
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise ValueError("请先保存角色再生成过渡")
    start, end = payload.get("fromPath"), payload.get("toPath")
    identity = transition_identity(character, start, end)
    roots = (
        _resolve_file_access_roots(state, file_access_roots)
        if file_access_roots
        else _local_file_access_roots(state)
    )
    first, last = [
        safe_existing_file_path(path, roots=roots, field="sprite")
        for path in (start, end)
    ]
    return character, first, last, identity


def _task(state, task_id, name):
    task = state.tasks.get(task_id)
    if (
        not task
        or task.get("kind") != "character-sprite-transition"
        or task.get("status") != "succeeded"
    ):
        raise ValueError("过渡结果不可用，请重新生成")
    if (task.get("result") or {}).get("name") != name:
        raise ValueError("过渡结果不属于当前角色")
    return task


def _unchanged(result, identity):
    if any(
        result.get(key) != identity[key]
        for key in ("fromPath", "toPath", "fromFingerprint", "toFingerprint")
    ):
        raise ValueError("来源立绘已变化，请重新生成过渡")


def run_sprite_transition(
    state, task_id, payload, *, file_access_roots: Iterable[Path] = ()
):
    matting_options(payload)
    if not isinstance(payload.get("regenerate", False), bool):
        raise ValueError("regenerate 必须为布尔值")
    if payload.get("retryTaskId") is not None and not isinstance(
        payload["retryTaskId"], str
    ):
        raise ValueError("retryTaskId 必须为任务编号")
    character, first, last, identity = _endpoints(
        state, payload, file_access_roots=file_access_roots
    )
    if payload.get("retryTaskId"):
        with state.task_lock:
            source = dict(
                _task(state, payload["retryTaskId"], identity["name"])["result"]
            )
        _unchanged(source, identity)
        if source.get("requestedFrames") != TRANSITION_FRAME_COUNT:
            raise ValueError("这是旧版过渡，请重绘生成 22 帧版本")
        source = retry_animation_matting(source, payload)
    else:
        if not payload.get("regenerate", False):
            for edge in saved_transitions(character):
                if (
                    edge["fromPath"] == identity["fromPath"]
                    and edge["toPath"] == identity["toPath"]
                    and edge["frameCount"] == TRANSITION_FRAME_COUNT
                ):
                    return {
                        **identity,
                        "taskId": task_id,
                        "path": edge["path"],
                        "cached": True,
                        "alphaVerified": True,
                        "frameCount": TRANSITION_FRAME_COUNT,
                    }
        root = Path(state.project_root_dir) / "cache" / "sprite_generation"
        _update_task(
            state,
            task_id,
            phase="generate",
            progress=0.05,
            message="正在用首尾帧生成 22 帧固定镜头过渡与随动头发。",
        )
        first = boundary_frame(first, root / f"{task_id}-first.png", last=True)
        last = boundary_frame(last, root / f"{task_id}-last.png", last=False)
        source = {
            **render_transition(
                state.config_manager,
                {**payload, **identity},
                root / f"{task_id}.png",
                first,
                last,
            ),
            **identity,
        }
    result = _finish_animation(state, task_id, source)
    if (
        result.get("alphaVerified")
        and result.get("frameCount") != TRANSITION_FRAME_COUNT
    ):
        raise ValueError("工作流未返回 22 帧过渡，请检查 H3 工作流")
    return result


def save_sprite_transitions(
    state, payload, *, file_access_roots: Iterable[Path] = ()
):
    name = str(payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("请选择要保存的过渡")
    with state.task_lock:
        results, tasks, seen = [], [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("无效的过渡结果")
            task_id = str(item.get("taskId") or "")
            if task_id in seen:
                continue
            seen.add(task_id)
            task = _task(state, task_id, name)
            result = task["result"]
            _, _, _, identity = _endpoints(
                state,
                {
                    "name": name,
                    "fromPath": result["fromPath"],
                    "toPath": result["toPath"],
                },
                file_access_roots=file_access_roots,
            )
            _unchanged(result, identity)
            if result.get("imported") or result.get("cached"):
                continue
            path = safe_existing_file_path(
                result["path"],
                roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
                field="transition",
            )
            if not result.get("alphaVerified") or path.suffix.lower() != ".webm":
                raise ValueError("请先完成过渡的透明处理")
            if verify_transparent_animation(path) != TRANSITION_FRAME_COUNT:
                raise ValueError("过渡必须为 22 帧透明视频")
            results.append({**result, "path": path.as_posix()})
            tasks.append(task)
        if results:
            state.character_manager.save_sprite_transitions(name, results)
            for task in tasks:
                task["result"] = {**task["result"], "imported": True}
    state.config_manager.reload()
    return _jsonify(state.config_manager.get_character_by_name(name))
