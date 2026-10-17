import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat import conversation_library as conversations
from application.chat.voice_archive import VoiceArchive
from core.chat_history.storage import remove_chat_history_storage


VOICE_ID = "a" * 32


@pytest.fixture
def voice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clip = tmp_path / "cache/audio/0.wav"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"first segment")
    session = tmp_path / "data/chat_history/session"
    return VoiceArchive(session), clip, session


def test_partial_voice_cannot_be_replayed_or_saved(voice):
    archive, clip, _ = voice
    archive.record(VOICE_ID, str(clip))
    assert not archive.has_voice(VOICE_ID)
    with pytest.raises(ValueError, match="生成"):
        archive.count(VOICE_ID)
    with pytest.raises(ValueError, match="生成"):
        archive.save_voice(VOICE_ID)


def test_legacy_index_remains_readable_and_new_segments_require_completion(voice):
    archive, clip, session = voice
    archive.audio_dir.mkdir(parents=True)
    segment = {"cache": str(clip), "sha256": hashlib.sha256(clip.read_bytes()).hexdigest()}
    archive.index_path.write_text(json.dumps({"voices": {VOICE_ID: [segment]}}), encoding="utf-8")
    reopened = VoiceArchive(session)
    assert reopened.source(VOICE_ID, 0) == clip
    reopened.record(VOICE_ID, str(clip), dialog_id="invalid metadata")
    assert not reopened.has_voice(VOICE_ID)
    reopened.complete(VOICE_ID)
    assert VoiceArchive(session).count(VOICE_ID) == 2


@pytest.mark.parametrize("remove", ["storage", "conversation"])
def test_deleting_session_removes_owned_audio_and_allows_path_reuse(voice, remove, tmp_path):
    archive, clip, session = voice
    archive.record(VOICE_ID, str(clip))
    archive.set_enabled(True)
    # Exercise both archive locations without relying on replay readiness.
    saved = session / "audio/save" / f"{VOICE_ID}-0.wav"
    saved.parent.mkdir()
    saved.write_bytes(clip.read_bytes())
    (session / "active.json").write_text("[]", encoding="utf-8")
    if remove == "storage":
        remove_chat_history_storage(session)
    else:
        state = SimpleNamespace(
            project_root_dir=tmp_path, history_dir=tmp_path / "data/chat_history",
            template_dir_path=tmp_path / "templates", chat_session={},
        )
        conversations.remember_conversation(state, session, {})
        conversations.delete_conversation(state, conversations._id(session))
        assert not conversations.list_conversations(state)
    assert not session.exists()
    assert clip.is_file()  # Shared synthesis cache belongs to its own owner.
    from application.chat.history.paths import resolve_history_path_for_project
    state = SimpleNamespace(project_root_dir=tmp_path, history_dir=tmp_path / "data/chat_history")
    assert resolve_history_path_for_project(state, session) == session


def test_index_replacement_never_truncates_current_index(voice, monkeypatch):
    archive, _, _ = voice
    archive.set_enabled(False)
    original = archive.index_path.read_bytes()
    write_text = Path.write_text

    def reject_in_place_write(path, *args, **kwargs):
        assert path != archive.index_path, "must publish a complete replacement index"
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", reject_in_place_write)
    archive.set_enabled(True)
    assert json.loads(original)["enabled"] is False
    assert json.loads(archive.index_path.read_bytes())["enabled"] is True


@pytest.mark.parametrize("failure", ["sync", "replace"])
def test_failed_index_commit_preserves_published_and_in_memory_state(voice, monkeypatch, failure):
    from application.chat import voice_archive

    archive, clip, _ = voice
    archive.record(VOICE_ID, str(clip))
    original = archive.index_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk failure")

    if failure == "sync":
        monkeypatch.setattr(voice_archive.os, "fsync", fail)
    else:
        monkeypatch.setattr(voice_archive, "durable_rename", fail)
    with pytest.raises(OSError, match="disk failure"):
        archive.complete(VOICE_ID)
    assert archive.index_path.read_bytes() == original
    assert not archive.has_voice(VOICE_ID)
    assert not list(archive.audio_dir.glob(".voice-index-*.tmp"))


def test_reader_sees_whole_index_before_and_after_publication(voice, monkeypatch):
    from application.chat import voice_archive

    archive, clip, _ = voice
    archive.record(VOICE_ID, str(clip))
    reader = VoiceArchive(archive.audio_dir.parent)
    publish = voice_archive.durable_rename

    def inspect(temporary, destination, **kwargs):
        assert json.loads(temporary.read_text(encoding="utf-8"))["voices"][VOICE_ID]["complete"]
        reader.refresh()
        assert not reader.has_voice(VOICE_ID)
        publish(temporary, destination, **kwargs)
        reader.refresh()
        assert reader.count(VOICE_ID) == 1

    monkeypatch.setattr(voice_archive, "durable_rename", inspect)
    archive.complete(VOICE_ID)


def test_unreadable_initial_index_is_not_silently_overwritten(voice):
    archive, _, session = voice
    archive.audio_dir.mkdir(parents=True)
    archive.index_path.write_text('{"voices":', encoding="utf-8")
    with pytest.raises(ValueError):
        VoiceArchive(session)


def test_deletion_preserves_unrelated_audio_files(voice):
    archive, clip, session = voice
    archive.record(VOICE_ID, str(clip))
    archive.complete(VOICE_ID)
    archive.set_enabled(True)
    archive.save_voice(VOICE_ID)
    notes = archive.audio_dir / "notes.txt"
    notes.write_text("user file", encoding="utf-8")
    remove_chat_history_storage(session)
    assert list(archive.audio_dir.iterdir()) == [notes]
    assert notes.read_text(encoding="utf-8") == "user file"


def test_deletion_does_not_follow_external_audio_directory(voice, tmp_path):
    archive, clip, session = voice
    external = tmp_path / "external"
    external.mkdir()
    kept = external / f"{VOICE_ID}-0.wav"
    kept.write_bytes(clip.read_bytes())
    session.mkdir(parents=True)
    try:
        archive.audio_dir.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable on this host")
    remove_chat_history_storage(session)
    assert kept.read_bytes() == clip.read_bytes()


@pytest.mark.parametrize("invalid", ['{"voices":', '{"voices":{},"dialogs":[]}', '{"voices":{"broken":[]}}'])
def test_bridge_reader_keeps_last_valid_index_and_refreshes_valid_replacement(voice, tmp_path, invalid):
    from application.chat.composition import _chat_voice_info

    archive, clip, session = voice
    (session / "audio").mkdir(parents=True)
    (session / "active.json").write_text("[]", encoding="utf-8")
    segment = {"cache": str(clip), "sha256": hashlib.sha256(clip.read_bytes()).hexdigest()}
    data = {"enabled": False, "voices": {VOICE_ID: [segment]}}
    archive.index_path.write_text(json.dumps(data), encoding="utf-8")
    state = SimpleNamespace(
        project_root_dir=tmp_path, history_dir=tmp_path / "data/chat_history",
        chat_session={"historyPath": str(session)},
    )
    assert _chat_voice_info(state, VOICE_ID) == {"segmentCount": 1}
    archive.index_path.write_text(invalid, encoding="utf-8")
    assert _chat_voice_info(state, VOICE_ID) == {"segmentCount": 1}
    data["voices"][VOICE_ID].append(segment)
    archive.index_path.write_text(json.dumps(data), encoding="utf-8")
    assert _chat_voice_info(state, VOICE_ID) == {"segmentCount": 2}
    archive.index_path.unlink()
    with pytest.raises(ValueError, match="不存在"):
        _chat_voice_info(state, VOICE_ID)


@pytest.mark.parametrize("recovery", ["normal-close", "interrupted-journal"])
def test_restart_restores_duplicate_dialog_voices_before_first_history_sync(voice, monkeypatch, recovery):
    from ai.llm.history_manager import HistoryManager
    from application.chat.history.branches import ConversationBranchManager
    from application.chat.presentation.updates import StreamingUIUpdateManager
    from application.media.resource_urls import UnconfiguredResourceUrls
    from core.chat_history.identity import DialogIdentities, CHAT_TURN_ID
    from core.chat_history.storage import save_branch_state

    archive, clip, session = voice
    dialog = {"character_name": "Alice", "speech": "Same words", "sprite": "1"}
    identities = DialogIdentities("c" * 32)
    dialog_ids = [identities.next(dialog), identities.next(dialog)]
    assert dialog_ids[0] != dialog_ids[1]
    assert DialogIdentities("e" * 32).next(dialog) not in dialog_ids
    for dialog_id, voice_id in zip(dialog_ids, (VOICE_ID, "b" * 32)):
        archive.record(voice_id, str(clip), dialog_id=dialog_id)
        archive.complete(voice_id)
    archive.set_enabled(True)
    messages = [
        {"role": "user", "content": "Say it twice", CHAT_TURN_ID: "c" * 32},
        {"role": "assistant", "content": json.dumps({"dialog": [dialog, dialog]})},
    ]
    active = session / "active.json"
    monkeypatch.setattr(HistoryManager, "_instance", None)
    history = []
    storage = HistoryManager(history)
    if recovery == "normal-close":
        assert storage.save_chat_history(str(active), messages)
    else:
        assert storage.save_chat_history(str(active), [])
        for message in messages:
            storage.append_message_to_tmp(str(active), message)
    save_branch_state(session, {
        "active": "main", "counter": 1,
        "branches": {"main": {"id": "main", "messages": [], "history": ["stale HTML"]}},
    })
    loaded = storage.load_chat_history(str(active))
    manager = ConversationBranchManager(
        history_path=str(session), chat_history=history,
        bindings=SimpleNamespace(get_messages=lambda: loaded, set_messages=Mock()),
    )
    manager.load(loaded, active_history_present=True)
    assert "stale HTML" not in history
    sink = Mock()
    ui = StreamingUIUpdateManager(sink, chat_history=history, resource_urls=UnconfiguredResourceUrls())
    ui.voice_archive = VoiceArchive(session)
    ui.sync_history_entries()
    entries = sink.emit.call_args.args[0]["entries"]
    assert [entry.get("voiceId") for entry in entries if entry["role"] == "assistant"] == [VOICE_ID, "b" * 32]


@pytest.mark.parametrize("ending", ["success", "missing", "synthesis-error", "record-error"])
def test_lazy_segmented_tts_publishes_replay_only_after_successful_completion(
    voice, mock_app_runtime, monkeypatch, ending,
):
    from application.chat.dialog_media import ResolvedSpriteAsset
    from application.chat.presentation.handlers.dialog_media import CharacterMediaHandler
    from application.chat.presentation.updates import StreamingUIUpdateManager
    from application.media.resource_urls import UnconfiguredResourceUrls
    from sdk.messages import LLMDialogMessage

    archive, clip, session = voice
    sink = Mock()
    ui = StreamingUIUpdateManager(sink, chat_history=[], resource_urls=UnconfiguredResourceUrls())
    ui.voice_archive = archive
    mock_app_runtime.ui_update_manager = ui
    generated = []
    outputs = []

    def synthesize(_request):
        for index in range(3):
            if index == 2 and ending == "synthesis-error":
                raise RuntimeError("synthesis failed")
            path = clip.with_name(f"{index}.wav")
            path.write_bytes(f"segment {index}".encode())
            generated.append(path)
            yield "" if index == 2 and ending == "missing" else str(path)

    if ending == "record-error":
        record = archive.record

        def fail_last(voice_id, path, **kwargs):
            if Path(path).name == "2.wav":
                raise OSError("archive failed")
            return record(voice_id, path, **kwargs)

        monkeypatch.setattr(archive, "record", fail_last)

    def present(output):
        outputs.append(output)
        if len(outputs) == 1:
            assert len(generated) == 2  # Third segment has not even started.
            assert output.dialog_id == "d" * 64
            ui.update_dialog(output.name, output.text, "#fff", False, output.voice_id, output.dialog_id)
            snapshot = sink.emit.call_args.args[0]
            assert snapshot["type"] == "history.replace"
            assert "voiceId" not in snapshot["entries"][0]
            reader = VoiceArchive(session)
            with pytest.raises(ValueError, match="生成"):
                reader.count(output.voice_id)
            with pytest.raises(ValueError, match="生成"):
                reader.source(output.voice_id, 0)
            with pytest.raises(ValueError, match="生成"):
                reader.save_voice(output.voice_id)

    mock_app_runtime.presentation_queue = SimpleNamespace(put=present)
    resolver = Mock()
    resolver.candidates.return_value = ()
    resolver.resolve.return_value = ResolvedSpriteAsset(asset_id="1")
    handler = CharacterMediaHandler(
        sprite_resolver=resolver,
        tts_generation_strategy=SimpleNamespace(generate=synthesize),
    )
    message = LLMDialogMessage(name="TestChar", text="One. Two. Three.", dialog_id="d" * 64)
    if ending == "synthesis-error":
        with pytest.raises(RuntimeError, match="synthesis failed"):
            handler.handle(message)
    else:
        handler.handle(message)
    voice_id = outputs[0].voice_id
    reader = VoiceArchive(session)
    ui.sync_history_entries()
    entry = sink.emit.call_args.args[0]["entries"][0]
    if ending == "success":
        assert reader.count(voice_id) == 3
        assert entry["voiceId"] == voice_id
        assert [reader.source(voice_id, i).read_bytes() for i in range(3)] == [
            f"segment {i}".encode() for i in range(3)
        ]
    else:
        assert not reader.has_voice(voice_id)
        assert "voiceId" not in entry
