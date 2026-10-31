"""Task ownership and persistence for directed sprite transitions."""

from pathlib import Path

from application.characters.transition_sprites import (
    render_transition,
    transition_identity,
    saved_transitions,
    TRANSITION_FRAME_COUNT,
)
from application.characters.animate_sprites import verify_transparent_animation
from application.characters.generate_sprites import boundary_frame
from application.characters.transition_recommendations import (
    analyze_transition_recommendations,
)
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
from frontend_bridge_core.sprite_generation import _finish_animation
from frontend_bridge_core.tools import _local_file_access_roots
from sdk.path_utils import safe_existing_file_path


def run_transition_analysis(state, task_id, payload):
    _update_task(state, task_id, progress=0.1, message="正在读取该角色的最近聊天。")
    result = analyze_transition_recommendations(
        state,
        payload,
        progress=lambda message: _update_task(
            state, task_id, progress=0.4, message=message
        ),
    )
    _update_task(state, task_id, progress=1.0, message="单向过渡推荐已完成。")
    return result


def _endpoints(state, payload):
    name = str(payload.get("name") or "").strip()
    character = state.config_manager.get_character_by_name(name)
    if character is None:
        raise ValueError("请先保存角色再生成过渡")
    start, end = payload.get("fromPath"), payload.get("toPath")
    identity = transition_identity(character, start, end)
    first, last = [
        safe_existing_file_path(
            path, roots=_local_file_access_roots(state), field="sprite"
        )
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


def run_sprite_transition(state, task_id, payload):
    if not isinstance(payload.get("regenerate", False), bool):
        raise ValueError("regenerate 必须为布尔值")
    if payload.get("retryTaskId") is not None and not isinstance(
        payload["retryTaskId"], str
    ):
        raise ValueError("retryTaskId 必须为任务编号")
    character, first, last, identity = _endpoints(state, payload)
    if payload.get("retryTaskId"):
        with state.task_lock:
            source = dict(
                _task(state, payload["retryTaskId"], identity["name"])["result"]
            )
        _unchanged(source, identity)
        if source.get("requestedFrames") != TRANSITION_FRAME_COUNT:
            raise ValueError("这是旧版过渡，请重绘生成 22 帧版本")
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
                state.config_manager, identity, root / f"{task_id}.png", first, last
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


def save_sprite_transitions(state, payload):
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
