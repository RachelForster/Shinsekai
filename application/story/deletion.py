"""Delete one library version and the conversations bound to that version."""

from pathlib import Path
from typing import Any

from application.chat import conversation_library as conversations
from application.chat.history_paths import resolve_history_path_for_project
from application.chat.runtime_process import _chat_runtime_status
from application.chat.start_chat import _chat_init_lock
from application.story.coordinator import clear_story_session
from application.story.library import _matches, _read_project, list_story_library
from core.chat_history.storage import STORY_SESSION_FILENAME, chat_history_session_dir
from sdk.path_utils import safe_existing_file_path


def _story_file(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    return path / "manifest.yaml" if path.is_dir() else path


def _associated_histories(state: Any, story: Path, program: Any) -> list[Path]:
    root = Path(state.project_root_dir).resolve()
    records = conversations._records(state)
    # Include registered conversations whose active history is missing, and old
    # saves created before the named-conversation registry existed.
    for metadata in conversations._directory(state).glob("*.json"):
        record = conversations._read(metadata)
        if (
            isinstance(record, dict)
            and isinstance(record.get("historyPath"), str)
            and record["historyPath"]
        ):
            path = root / record["historyPath"]
            records.setdefault(conversations._id(path), record)
    history_root = Path(state.history_dir).resolve()
    for filename in (STORY_SESSION_FILENAME, "story-prompt-binding.json"):
        for file in history_root.rglob(filename):
            directory = file.parent.resolve()
            if directory.is_relative_to(history_root):
                records.setdefault(conversations._id(directory), {"historyPath": str(directory)})

    selected = []
    for record in records.values():
        path = root / record["historyPath"]
        directory = chat_history_session_dir(path)
        binding = conversations._read(directory / "story-prompt-binding.json")
        binding = binding if isinstance(binding, dict) else {}
        launch = record.get("launch")
        launch = launch if isinstance(launch, dict) else {}
        source = binding.get("storyPath") or launch.get("storyPath")
        if isinstance(source, str) and source:
            matches = _story_file(root, source) == story
        else:
            saved = conversations._read(directory / STORY_SESSION_FILENAME)
            matches = isinstance(saved, dict) and _matches(saved, program)
        if matches:
            # Orphan sidecars are already bounded by the managed history root.
            if (
                path == directory
                and directory.resolve().is_relative_to(history_root)
                and not (directory / "active.json").exists()
            ):
                path = directory.resolve()
            else:
                path = resolve_history_path_for_project(state, path)
            selected.append(path)
    return selected


def delete_story_version(state: Any, story_path: str) -> dict:
    root = Path(state.project_root_dir).resolve()
    if not story_path.strip():
        raise ValueError("请选择要删除的剧本版本。")
    story = safe_existing_file_path(
        _story_file(root, story_path),
        roots=(root / "data/stories",),
        field="story path",
    )
    with _chat_init_lock(state), conversations._metadata_lock:
        if getattr(state, "chat_init_task_id", ""):
            raise RuntimeError("请等待聊天初始化完成后再删除剧本。")
        if not any(Path(item["storyPath"]) == story for item in list_story_library(state)):
            raise ValueError("该剧本版本不在已有剧本中，请刷新后重试。")
        _, _, program = _read_project(state, story)
        histories = _associated_histories(state, story, program)
        active = getattr(state, "chat_session", {})
        active_history = active.get("historyPath")
        active_selected = bool(active_history) and conversations._id(root / active_history) in {
            conversations._id(path) for path in histories
        }
        active_source = active.get("storyPath")
        active_selected = active_selected or bool(
            active_source and _story_file(root, active_source) == story
        )
        if active_selected and _chat_runtime_status(state)["state"] != "idle":
            raise RuntimeError("请先关闭该剧本版本的聊天，再删除剧本及关联对话。")
        if active_selected:
            clear_story_session(state)
        # Preflight every association before changing any files. Keep the source
        # until history cleanup succeeds so a failed deletion can be retried.
        for path in histories:
            conversations._delete_conversation_files(state, path)
        story.unlink()
        # Referenced cast/assets and sibling versions may be shared. Deleting a
        # version never recursively removes its containing directory.
        return {"ok": True, "deletedConversations": len(histories)}
