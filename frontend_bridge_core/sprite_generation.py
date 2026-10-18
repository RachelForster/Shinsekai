"""Task and persistence boundary for the character sprite generator."""

from pathlib import Path
from types import SimpleNamespace

from application.characters.generate_sprites import (
    plan_sprites,
    prompt_pair,
    render_sprite,
)
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
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


def run_sprite_render(state, task_id, payload):
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
    return {**result, "taskId": task_id}


def import_generated_sprites(state, payload):
    name = str(payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError("请选择 1–12 张生成的立绘")
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
            task = state.tasks.get(task_id)
            if (
                not task
                or task["kind"] != "character-sprite-render"
                or task["status"] != "succeeded"
            ):
                raise ValueError("立绘结果不可用，请重新生成")
            result = task.get("result") or {}
            if result.get("name") != name:
                raise ValueError("立绘结果不属于当前角色")
            if result.get("imported"):
                continue
            path = safe_existing_file_path(
                result["path"],
                roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
                field="generatedImage",
            )
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
                name, files, character.emotion_tags, sprite_tags=tags
            )
            for task in tasks:
                task["result"] = {**task["result"], "imported": True}
    state.config_manager.reload()
    return _jsonify(state.config_manager.get_character_by_name(name))
