from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.chat.conversation_library import (
    conversation_launch_payload,
    delete_conversation,
    list_conversations,
    remember_conversation,
    rename_conversation,
    saved_conversation_launch,
)
from application.chat.launch_history import plan_chat_history_launch


@pytest.fixture
def state(tmp_path):
    return SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(tmp_path / "history"),
        template_dir_path=str(tmp_path / "templates"),
        config_manager=SimpleNamespace(
            get_character_by_name=lambda name: name if name == "Alice" else None
        ),
    )


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def history(state, name="first"):
    path = Path(state.history_dir) / name
    write(
        path / "active.json",
        [
            {"role": "system", "content": "Original prompt"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "dialog": [
                            {
                                "character_name": "Alice",
                                "speech": "Good night",
                                "sprite": "1",
                            }
                        ]
                    }
                ),
            },
        ],
    )
    return path


def test_saved_launch_survives_template_and_selection_changes(state):
    path = history(state)
    payload = {
        "templateId": "one",
        "templateName": "Evening",
        "characters": ["Alice"],
        "scenario": "Old scene",
        "system": "Original prompt",
        "mediaSelectionMode": "semantic",
    }
    remember_conversation(state, path, payload)
    payload.update(scenario="New scene", system="Different prompt", characters=["Bob"])
    record = list_conversations(state)[0]
    restored = conversation_launch_payload(state, record["id"])
    assert restored["scenario"] == "Old scene"
    assert restored["characters"] == ["Alice"]
    assert restored["system"] == "Original prompt"
    assert restored["mediaSelectionMode"] == "semantic"
    assert restored["historyPath"] == path.as_posix()
    assert restored["resetHistory"] is False
    assert record["preview"] == "Good night"
    assert "Original prompt" not in json.dumps(record)


def test_chat_title_is_independent_of_template_name_and_keeps_renames(state):
    path = history(state)
    payload = {"templateName": "Template", "conversationTitle": "  My chat  "}
    remember_conversation(state, path, payload)
    item = list_conversations(state)[0]
    assert item["title"] == "My chat"
    assert conversation_launch_payload(state, item["id"])["templateName"] == "Template"
    rename_conversation(state, item["id"], "Renamed")
    remember_conversation(state, path, payload)
    assert list_conversations(state)[0]["title"] == "Renamed"


def test_delete_removes_history_branches_story_and_legacy_alias_but_keeps_other_files(state):
    path = history(state)
    write(path / "branches.json", {})
    write(path / "story-v2.json", {})
    write(path / "story-prompt-binding.json", {"storyPath": "original.json"})
    write(path.with_suffix(".json"), [])
    write(path / "keep.txt", "unrelated")
    other = history(state, "second")
    remember_conversation(state, path, {"characters": ["Alice"]})
    item = next(item for item in list_conversations(state) if item["historyPath"] == path.as_posix())
    delete_conversation(state, item["id"])
    assert not (path / "active.json").exists()
    assert not path.with_suffix(".json").exists()
    assert list(path.iterdir()) == [path / "keep.txt"]
    assert (other / "active.json").is_file()
    assert len(list_conversations(state)) == 1
    assert saved_conversation_launch(state, path) is None


@pytest.mark.parametrize("busy", ["initializing", "running", "closing"])
def test_delete_rejects_active_sessions(state, monkeypatch, busy):
    path = history(state)
    state.chat_session = {"historyPath": str(path)}
    if busy == "initializing":
        state.chat_init_task_id = "task"
    monkeypatch.setattr("application.chat.runtime_process._chat_runtime_status", lambda _state: {"state": busy})
    item = list_conversations(state)[0]
    with pytest.raises(RuntimeError):
        delete_conversation(state, item["id"])
    assert (path / "active.json").is_file()


def test_rename_keeps_storage_branch_links_and_title_on_relaunch(state):
    path = history(state)
    write(path / "branches.json", {"parent": "unchanged"})
    remember_conversation(state, path, {"characters": ["Alice"], "system": "original"})
    item = list_conversations(state)[0]
    rename_conversation(state, item["id"], "My evening")
    remember_conversation(state, path, {"characters": ["Alice"], "system": "edited"})
    assert list_conversations(state)[0]["title"] == "My evening"
    assert json.loads((path / "branches.json").read_text()) == {"parent": "unchanged"}
    assert saved_conversation_launch(state, path)["system"] == "edited"


def test_legacy_discovery_does_not_write_or_guess_last_template(state):
    path = history(state)
    original = (path / "active.json").read_bytes()
    items = list_conversations(state)
    assert items[0]["hasSettings"] is False
    assert not (Path(state.template_dir_path).parent / "config").exists()
    payload = conversation_launch_payload(state, items[0]["id"])
    assert payload["system"] == "Original prompt"
    assert payload["characters"] == ["Alice"]
    assert (path / "active.json").read_bytes() == original


@pytest.mark.parametrize("saved_settings", [False, True])
def test_default_title_and_participants_exclude_dialog_control_roles(state, saved_settings):
    path = history(state)
    names = [
        "CHOICE", "COT", "NARR", "STAT", "SCENE", "bgm", "CG",
        "选项", "思维链", "旁白", "数值", "场景", " choice ", "BGM", "cg",
        " Alice ", "Bob", "Alice", "CHOICE Alice",
    ]
    write(path / "active.json", [{
        "role": "assistant",
        "content": json.dumps({"dialog": [
            {"character_name": name, "speech": "Hello"} for name in names
        ]}),
    }])
    if saved_settings:
        remember_conversation(state, path, {"characters": names})
    original = (path / "active.json").read_bytes()
    item = list_conversations(state)[0]
    assert item["characters"] == ["Alice", "Bob", "CHOICE Alice"]
    assert item["title"] == "Alice · Bob · CHOICE Alice"
    assert (path / "active.json").read_bytes() == original


def test_control_only_history_uses_untitled_fallback_and_preserves_authored_titles(state):
    path = history(state)
    write(path / "active.json", [{
        "role": "assistant",
        "content": '{"dialog": [{"character_name": "CHOICE", "speech": "Continue"}]}',
    }])
    item = list_conversations(state)[0]
    assert item["characters"] == []
    assert item["title"] == ""  # The UI supplies its localized untitled label.
    rename_conversation(state, item["id"], "My CHOICE story")
    assert list_conversations(state)[0]["title"] == "My CHOICE story"


def test_every_story_save_appears_separately(state):
    for name in ("play-one", "play-two"):
        path = history(state, name)
        write(path / "story-v2.json", {"activeBranchId": name})
        write(path / "story-prompt-binding.json", {"storyPath": "story.json"})
    entries = list_conversations(state)
    assert len(entries) == 2
    assert len({entry["id"] for entry in entries}) == 2
    assert all(
        entry["kind"] == "story" and entry["storyPath"] == "story.json"
        for entry in entries
    )


def test_migrated_legacy_alias_appears_only_once(state):
    path = history(state)
    write(path / "branches.json", {})
    write(path.with_suffix(".json"), [])
    assert len(list_conversations(state)) == 1


def test_external_explicit_history_is_listed_but_unregistered_external_file_is_not(
    state, tmp_path
):
    external = tmp_path / "elsewhere" / "record.json"
    write(external, [{"role": "user", "content": "Hello"}])
    assert list_conversations(state) == []
    remember_conversation(state, external, {"characters": ["Alice"]})
    entries = list_conversations(state)
    assert entries[0]["historyPath"] == external.as_posix()


def test_new_chats_never_reuse_a_template_derived_identity(state):
    payload = {"characters": ["Alice"]}
    first = plan_chat_history_launch(
        state, payload, {"scenario": "same"}, start_fresh=True
    )
    second = plan_chat_history_launch(
        state, payload, {"scenario": "same"}, start_fresh=True
    )
    assert first.history_path != second.history_path
    assert first.history_path.name.startswith("chat-")


@pytest.mark.parametrize("identifier", ["../../secret", "unknown"])
def test_unknown_id_cannot_read_or_write_arbitrary_paths(state, identifier):
    with pytest.raises(KeyError):
        conversation_launch_payload(state, identifier)
    with pytest.raises(KeyError):
        rename_conversation(state, identifier, "Renamed")
    with pytest.raises(KeyError):
        delete_conversation(state, identifier)


def test_missing_history_is_not_resurrected_from_metadata(state):
    path = history(state)
    remember_conversation(state, path, {"characters": ["Alice"]})
    (path / "active.json").unlink()
    assert list_conversations(state) == []


def test_registered_legacy_file_keeps_its_identity_after_branch_migration(state):
    legacy = Path(state.history_dir) / "old.json"
    write(legacy, [{"role": "user", "content": "Hello"}])
    remember_conversation(
        state, legacy, {"characters": ["Alice"], "system": "original"}
    )
    original_id = list_conversations(state)[0]["id"]
    directory = legacy.with_suffix("")
    write(directory / "active.json", [{"role": "user", "content": "Hello again"}])
    write(directory / "branches.json", {})
    entries = list_conversations(state)
    assert len(entries) == 1
    assert entries[0]["id"] == original_id
    assert entries[0]["hasSettings"] is True
    assert saved_conversation_launch(state, directory)["system"] == "original"
