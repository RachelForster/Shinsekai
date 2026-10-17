import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat import conversation_library as conversations
from application.story import deletion
from application.story.editor import read_story_document, save_story_document
from application.story.library import _read_project, list_story_library
from application.story.persistence import JsonStorySessionRepository
from application.story.prompt_turns import PromptTurnJournal
from core.chat_history.storage import STORY_SESSION_FILENAME
from frontend_bridge_core.routes.router import ApiRequest
from frontend_bridge_core.routes.story_routes import STORY_ROUTES
from test.unit.application.story.test_library import selected_story


@pytest.fixture
def story(tmp_path, monkeypatch):
    state, task, _, _ = selected_story(tmp_path)
    state.template_dir_path = tmp_path / "data/templates"
    state.chat_session = {}
    monkeypatch.setattr(deletion, "_chat_runtime_status", lambda state: {"state": "idle"})
    return state, Path(task["draftPath"])


def chat(state, name, story_path=None):
    path = state.history_dir / name
    conversations.remember_conversation(
        state, path, {"storyPath": str(story_path)} if story_path else {}
    )
    (path / "branches.json").write_text("{}", encoding="utf-8")
    if story_path:
        (path / "story-prompt-binding.json").write_text(
            json.dumps({"storyPath": str(story_path)}), encoding="utf-8"
        )
    return path


def test_deletes_selected_version_and_all_its_conversations_through_route(story):
    state, path = story
    document = read_story_document(state, str(path))
    other = save_story_document(state, document)
    other_path = Path(other["storyPath"])
    original_other = other_path.read_bytes()
    first = chat(state, "first", path)
    second = chat(state, "second", path.relative_to(state.project_root_dir))
    # A launch that has not attached the story runtime yet still belongs to it.
    (second / "story-prompt-binding.json").unlink()
    kept = chat(state, "other-version", other_path)
    normal = chat(state, "normal")
    (first / "user-notes.txt").write_text("keep me", encoding="utf-8")
    alias = Path(str(first) + ".json")
    alias.write_text("[]", encoding="utf-8")

    route = next(route for route in STORY_ROUTES if route.name == "story.library.delete")
    response = route.handler(ApiRequest(
        state=state, method="POST", path=route.pattern, query={}, params={},
        body={"storyPath": str(path)},
    ))

    assert response.data == {"ok": True, "deletedConversations": 2}
    assert not path.exists()
    assert not alias.exists()
    assert not second.exists()
    assert list(first.iterdir()) == [first / "user-notes.txt"]
    assert other_path.read_bytes() == original_other
    assert read_story_document(state, str(other_path))["version"] == other["version"]
    assert {row["historyPath"] for row in conversations.list_conversations(state)} == {
        kept.as_posix(), normal.as_posix(),
    }
    assert [row["storyPath"] for row in list_story_library(state)] == [other_path.as_posix()]


def test_deletes_unregistered_saves_and_orphan_sidecars_by_exact_version(story):
    state, path = story
    _, _, program = _read_project(state, path)
    for name, version in (("selected", program.story_version), ("other", program.story_version + 1)):
        JsonStorySessionRepository(state.history_dir / name).save({
            "storyId": program.story_id, "storyVersion": version,
            "programSourceHash": program.source_hash,
        })
    result = deletion.delete_story_version(state, str(path))
    assert result["deletedConversations"] == 1
    assert not (state.history_dir / "selected").exists()
    assert (state.history_dir / "other" / STORY_SESSION_FILENAME).exists()


def test_legacy_directory_alias_can_be_deleted_without_touching_shared_files(story):
    state, original = story
    directory = state.project_root_dir / "data/stories/legacy"
    shutil.copytree(Path("test/fixtures/stories/campus-mystery"), directory)
    saved = chat(state, "legacy-chat", directory)
    remaining_files = {path: path.read_bytes() for path in directory.rglob("*") if path.is_file() and path.name != "manifest.yaml"}
    deletion.delete_story_version(state, str(directory))
    assert not (directory / "manifest.yaml").exists()
    assert not saved.exists()
    assert all(path.read_bytes() == content for path, content in remaining_files.items())
    assert original.is_file()


@pytest.mark.parametrize("runtime", ["running", "closing"])
def test_active_association_blocks_every_deletion_before_mutating(story, monkeypatch, runtime):
    state, path = story
    first = chat(state, "first", path)
    active = chat(state, "active", path)
    state.chat_session = {"historyPath": str(active)}
    monkeypatch.setattr(deletion, "_chat_runtime_status", lambda state: {"state": runtime})
    with pytest.raises(RuntimeError, match="先关闭"):
        deletion.delete_story_version(state, str(path))
    assert path.exists()
    assert (first / "active.json").exists()
    assert (active / "active.json").exists()


def test_pending_initialization_blocks_deletion(story):
    state, path = story
    state.chat_init_task_id = "starting"
    with pytest.raises(RuntimeError, match="初始化"):
        deletion.delete_story_version(state, str(path))
    assert path.exists()


def test_other_running_story_does_not_block_deletion(story, monkeypatch):
    state, path = story
    other = save_story_document(state, read_story_document(state, str(path)))
    active = chat(state, "other", other["storyPath"])
    state.chat_session = {"historyPath": str(active), "storyPath": other["storyPath"]}
    monkeypatch.setattr(deletion, "_chat_runtime_status", lambda state: {"state": "running"})
    deletion.delete_story_version(state, str(path))
    assert (active / "active.json").exists()
    assert Path(other["storyPath"]).exists()


def test_source_survives_failed_history_cleanup_for_retry(story, monkeypatch):
    state, path = story
    saved = chat(state, "locked", path)
    def fail(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(conversations, "_delete_conversation_files", fail)
    with pytest.raises(PermissionError):
        deletion.delete_story_version(state, str(path))
    assert path.exists()
    assert (saved / "active.json").exists()


def test_cannot_delete_project_files_outside_story_library(story):
    state, path = story
    outside = state.project_root_dir / "unrelated.json"
    outside.write_bytes(path.read_bytes())
    with pytest.raises(PermissionError):
        deletion.delete_story_version(state, str(outside))
    assert outside.exists()
    assert path.exists()


def test_explicit_other_source_wins_over_identical_story_identity(story):
    state, path = story
    duplicate = path.with_name("edited-copy.json")
    duplicate.write_bytes(path.read_bytes())
    saved = chat(state, "copy", duplicate)
    _, _, program = _read_project(state, path)
    JsonStorySessionRepository(saved).save({
        "storyId": program.story_id, "storyVersion": program.story_version,
        "programSourceHash": program.source_hash,
    })
    deletion.delete_story_version(state, str(path))
    assert duplicate.exists()
    assert (saved / "active.json").exists()


@pytest.mark.parametrize("has_history", [False, True])
def test_ambiguous_identity_preserves_unregistered_source_less_save(story, has_history):
    state, path = story
    duplicate = path.with_name("edited-copy.json")
    duplicate.write_bytes(path.read_bytes())
    _, _, program = _read_project(state, path)
    legacy = state.history_dir / "legacy-copy"
    repository = JsonStorySessionRepository(legacy)
    repository.save({
        "storyId": program.story_id, "storyVersion": program.story_version,
        "programSourceHash": program.source_hash,
    })
    if has_history:
        (legacy / "active.json").write_text('[{"role":"user","content":"keep"}]', encoding="utf-8")
        PromptTurnJournal(str(legacy)).save({"message": {"content": "keep pending reply"}})
    originals = {file: file.read_bytes() for file in legacy.iterdir()}
    explicit = chat(state, "explicit-original", path)

    result = deletion.delete_story_version(state, str(path))

    assert result["deletedConversations"] == 1
    assert not explicit.exists()
    assert duplicate.exists()
    assert {file: file.read_bytes() for file in legacy.iterdir()} == originals


def test_story_deletion_removes_pending_prompt_turn(story):
    state, path = story
    saved = chat(state, "interrupted", path)
    journal = PromptTurnJournal(str(saved))
    journal.save({"message": {"content": "private reply"}, "history": ["private history"]})

    deletion.delete_story_version(state, str(path))

    assert not journal.path.exists()
    assert not saved.exists()


@pytest.mark.parametrize("failure", ["later-history", "source"])
def test_failed_bulk_deletion_restores_every_file_and_keeps_session(story, monkeypatch, failure):
    state, path = story
    first = chat(state, "first", path)
    second = chat(state, "second", path)
    for saved in (first, second):
        PromptTurnJournal(str(saved)).save({"message": {"content": saved.name}})
        audio = saved / "audio"
        (audio / "save").mkdir(parents=True)
        (audio / "index.json").write_text('{"voices":{}}', encoding="utf-8")
        (audio / f"{'a' * 32}-0.wav").write_bytes(b"archived voice")
        (audio / "save" / f"{'a' * 32}-0.wav").write_bytes(b"manually saved voice")
        Path(str(saved) + ".json").write_text("legacy", encoding="utf-8")
        (saved / "active.json.tmp").write_text("pending", encoding="utf-8")
        (saved / f"{STORY_SESSION_FILENAME}.lock").touch()
    closer = Mock()
    state.story_session = SimpleNamespace(close=closer)
    state.chat_session = {"historyPath": str(first)}
    originals = {
        file: file.read_bytes()
        for file in state.project_root_dir.rglob("*") if file.is_file()
    }
    if failure == "later-history":
        remove = conversations._delete_conversation_files
        calls = []

        def fail_later(state, history):
            calls.append(history)
            if len(calls) == 2:
                raise PermissionError("later history is locked")
            remove(state, history)

        monkeypatch.setattr(conversations, "_delete_conversation_files", fail_later)
    else:
        unlink = Path.unlink

        def fail_source(target, *args, **kwargs):
            if target == path:
                raise PermissionError("source is locked")
            return unlink(target, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_source)

    with pytest.raises(PermissionError, match="locked"):
        deletion.delete_story_version(state, str(path))

    assert {file: file.read_bytes() for file in originals} == originals
    assert len(conversations.list_conversations(state)) == 2
    closer.assert_not_called()


def test_idle_disconnected_stream_cannot_rehydrate_deleted_story(story):
    from application.chat.host.projection import SnapshotProjection
    from application.story.coordinator import story_snapshot_patch
    from frontend_bridge_core.chat_stream import ChatStreamService

    state, path = story
    saved = chat(state, "disconnected", path)
    state.chat_stream = stream = ChatStreamService(host="127.0.0.1", bridge_port=0)
    session = stream.create_session({"story": {"title": "deleted story"}})
    session_id = session["sessionId"]
    producer = SimpleNamespace(role="producer", session_id=session_id)
    stream._sessions[session_id].producer = producer
    asyncio.run(stream._detach(producer))
    assert stream.get_snapshot(session_id)["story"]["title"] == "deleted story"
    unrelated = stream.create_session({"story": {"title": "other story"}})["sessionId"]
    state.chat_session = {"historyPath": str(saved), "storyPath": str(path), **session}
    state.story_session = SimpleNamespace(close=Mock())

    deletion.delete_story_version(state, str(path))

    assert stream.get_snapshot(session_id) is None
    assert stream.get_snapshot(session_id, renderer_id="reconnected") is None
    assert state.chat_session["sessionId"] == ""
    assert state.story_session is None
    projection = SnapshotProjection(
        history=lambda _: [], running=lambda: False,
        story_patch=story_snapshot_patch, mobile_info=lambda _: None,
    )
    assert not projection.build(state).get("story")
    assert stream.get_snapshot(unrelated)["story"]["title"] == "other story"


def test_registered_external_history_preserves_unrelated_files(story):
    state, path = story
    external = state.project_root_dir / "external-history"
    external.mkdir()
    (external / "active.json").write_text("[]", encoding="utf-8")
    (external / "notes.txt").write_text("keep", encoding="utf-8")
    conversations.remember_conversation(state, external, {"storyPath": str(path)})
    result = deletion.delete_story_version(state, str(path))
    assert result["deletedConversations"] == 1
    assert list(external.iterdir()) == [external / "notes.txt"]
    assert not conversations.list_conversations(state)


def test_closed_current_story_releases_runtime_state(story):
    state, path = story
    saved = chat(state, "closed", path)
    closer = Mock()
    state.story_session = SimpleNamespace(close=closer)
    state.chat_session = {"historyPath": str(saved)}
    deletion.delete_story_version(state, str(path))
    closer.assert_called_once_with()
    assert state.story_session is None


def test_active_story_without_persisted_history_is_protected(story, monkeypatch):
    state, path = story
    state.chat_session = {"storyPath": str(path)}
    monkeypatch.setattr(deletion, "_chat_runtime_status", lambda state: {"state": "running"})
    with pytest.raises(RuntimeError, match="先关闭"):
        deletion.delete_story_version(state, str(path))
    assert path.exists()
