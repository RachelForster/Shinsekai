"""Discover playable projects and prepare launches with their saved progress."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from application.chat.history_paths import resolve_history_path_for_project
from application.chat.runtime_process import TRANSPARENT_BACKGROUND_NAME
from application.story.persistence import JsonStorySessionRepository
from application.story.project_loader import load_story_project
from application.story.selection import normal_template_options
from config.feature_flags import FeatureFlag
from core.chat_history.storage import STORY_SESSION_FILENAME, chat_history_session_dir
from core.story import CharacterSourceType, StoryCompiler, StoryValidationError
from sdk.path_utils import safe_existing_path


def _read_project(state: Any, story_path: str | Path):
    state.config_manager.feature_flags.require(FeatureFlag.STORY_SYSTEM)
    root = Path(state.project_root_dir).resolve()
    candidate = Path(story_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    path = safe_existing_path(candidate, roots=(root,), field="story path")
    project = load_story_project(path)
    return path, project, StoryCompiler().compile(project)


def _matches(saved: dict, program: Any) -> bool:
    return (
        saved.get("storyId") == program.story_id
        and saved.get("storyVersion") == program.story_version
        and saved.get("programSourceHash") == program.source_hash
    )


def list_story_library(state: Any) -> list[dict]:
    state.config_manager.feature_flags.require(FeatureFlag.STORY_SYSTEM)
    root = Path(state.project_root_dir).resolve()
    stories_root = root / "data" / "stories"
    histories = []
    history_root = Path(state.history_dir).resolve()
    for path in history_root.rglob(STORY_SESSION_FILENAME):
        try:
            safe_existing_path(path, roots=(history_root,), field="story save")
            saved = JsonStorySessionRepository(path.parent).load()
            if saved:
                histories.append((path.stat().st_mtime * 1000, path.parent, saved))
        except (OSError, ValueError):
            continue
    histories.sort(key=lambda item: item[0], reverse=True)
    entries = []
    for path in stories_root.rglob("*"):
        if path.suffix.lower() not in {".json", ".yaml", ".yml"} or not path.is_file():
            continue
        relative = path.relative_to(stories_root)
        if ".generation" in relative.parts:
            if path.name != "draft.json":
                continue
            try:
                task = json.loads(
                    path.with_name("task.json").read_text(encoding="utf-8")
                )
                if task.get("status") != "succeeded" or not (
                    task.get("validation") or {}
                ).get("valid"):
                    continue
            except (OSError, ValueError, AttributeError):
                continue
        try:
            resolved, project, program = _read_project(state, path)
            updated_at = path.stat().st_mtime * 1000
        except (OSError, ValueError, StoryValidationError):
            continue
        history = next((item for item in histories if _matches(item[2], program)), None)
        node_title = ""
        if history:
            saved = history[2]
            branch = saved.get("branches", {}).get(saved.get("activeBranchId"), {})
            node = program.nodes_by_id.get(branch.get("state", {}).get("currentNodeId"))
            node_title = node.title if node else ""
            updated_at = max(updated_at, history[0])
        entries.append(
            {
                "id": project.id,
                "title": project.title,
                "storyPath": resolved.as_posix(),
                "characters": [
                    str(item.source.character_id or item.id)
                    for item in project.character_registry.characters
                ],
                "backgrounds": list(project.metadata.backgrounds),
                "historyPath": history[1].as_posix() if history else "",
                "currentNodeTitle": node_title,
                "updatedAt": updated_at,
            }
        )
    return sorted(entries, key=lambda item: item["updatedAt"], reverse=True)


def prepare_story_launch(state: Any, story_path: str, history_path: str = "") -> dict:
    if not story_path.strip():
        raise ValueError("请选择剧本。")
    _, project, program = _read_project(state, story_path)
    if history_path:
        resolved_history = resolve_history_path_for_project(state, history_path)
        saved = JsonStorySessionRepository(
            chat_history_session_dir(resolved_history)
        ).load()
        if not saved or not _matches(saved, program):
            raise ValueError("存档与当前剧本不匹配，请刷新已有剧本后重试。")
        history_path = resolved_history.as_posix()
    bindings = project.metadata.resource_bindings
    names = list(
        bindings.get("characters")
        or [
            str(item.source.character_id or item.id)
            for item in project.character_registry.characters
            if item.source.type == CharacterSourceType.LOCAL_LIBRARY
        ]
    )
    names = [
        name
        for name in names
        if state.config_manager.get_character_by_name(name) is not None
    ]
    background = bindings.get("openingBackground") or TRANSPARENT_BACKGROUND_NAME
    payload = {
        **dict(bindings.get("templateOptions") or {}),
        **normal_template_options(state),
        "templateId": "",
        "templateName": project.title,
        "characters": names,
        "backgroundName": background,
        "characterPromptMode": bindings.get("characterPromptMode", "full"),
        "primaryCharacters": list(bindings.get("primaryCharacters", names)),
        "historyPath": history_path,
        "resetHistory": not bool(history_path),
        "scenario": bindings.get("scenario")
        or f"正在游玩互动剧本《{project.title}》。",
    }
    return payload
