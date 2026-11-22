from __future__ import annotations

import copy
import json
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat.history.replay import ChatReplayService
from application.chat.history.replay_store import ReplayRecorder, ReplayStore
from application.chat.voice_archive import VoiceArchive
from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.storage import remove_chat_history_storage
from sdk.messages import PresentationMessage


@pytest.fixture
def replay(tmp_path, monkeypatch):
    path = tmp_path / "chat" / "active.json"
    path.parent.mkdir()
    path.write_text("[]", encoding="utf-8")
    snapshot = {"status": "idle", "conversationTree": {"activeBranchId": "main", "branches": []}}
    character = SimpleNamespace(name="Mio", refer_audio_path="ref.wav", speech_volume=.6,
                                gpt_model_path="gpt", sovits_model_path="sovits", speech_speed=1,
                                prompt_text="reference", prompt_lang="en")
    config = SimpleNamespace(
        config=SimpleNamespace(system_config=SimpleNamespace(voice_language="en")),
        get_gpt_sovits_config=lambda: ("http://localhost:9880", "", "gpt-sovits"),
        merged_tts_factory_kwargs=lambda provider, kwargs: kwargs,
        get_character_by_name=lambda name: character if name == "Mio" else None,
    )
    source = [
        {"id": "history-0", "role": "user", "text": "You: hello"},
        {"id": "history-1", "role": "assistant", "text": "Mio: first", "dialogId": "a" * 64},
        {"id": "history-2", "role": "assistant", "text": "Mio: second", "dialogId": "b" * 64},
        {"id": "history-3", "role": "assistant", "text": "Mio: third", "dialogId": "c" * 64},
    ]
    state = SimpleNamespace(chat_session={"sessionId": "session", "historyPath": str(path)},
                            project_root_dir=str(tmp_path), config_manager=config,
                            chat_stream=SimpleNamespace(get_snapshot=lambda sid: snapshot, send_command=Mock(return_value=True)))
    monkeypatch.setattr("application.chat.history.replay.resolve_history_path_for_project", lambda state, raw: Path(raw))
    monkeypatch.setattr("application.chat.composition._chat_history", lambda state: copy.deepcopy(source))
    service = ChatReplayService(state)
    monkeypatch.setattr(service, "_prefetch", lambda plan: None)
    return service, source, snapshot, path


def begin(service, snapshot, start=0, end=None, generate=False):
    entries = snapshot["entries"]
    service.start(snapshot["id"], {"startKey": entries[start]["key"],
                                  "endKey": entries[end if end is not None else -1]["key"],
                                  "generate": generate})


def test_direct_replay_freezes_range_without_synthesis_or_chat_writes(replay):
    service, source, _, path = replay
    original = copy.deepcopy(source)
    service._synthesize = Mock(side_effect=AssertionError("must not synthesize"))
    snapshot = service.prepare()
    begin(service, snapshot, 1, 2)
    with pytest.raises(ValueError, match="未启用"):
        service.generate(snapshot["id"], snapshot["entries"][1]["key"])
    source.append({"id": "new", "role": "assistant", "text": "Mio: new"})
    assert len(snapshot["entries"]) == 4
    assert source[:-1] == original
    assert path.read_text() == "[]"
    assert not (path.parent / "replay").exists()


def test_replay_uses_the_original_user_input_without_internal_time_or_attachment_labels(replay):
    service, source, _, path = replay
    source[0].update(text="You: [本地时间 2026-11-09 22:00:00]\nhello [附件: sample.png]", revertUserIndex=0)
    path.write_text(json.dumps([{
        "role": "user", "content": "[本地时间 2026-11-09 22:00:00]\nhello [附件: sample.png]",
        "input_text": "hello",
    }], ensure_ascii=False), encoding="utf-8")
    source.insert(1, {"role": "user", "text": "You: [Local time 2026-11-09 22:01:00]\nlegacy [file:notes.txt]"})
    entries = service.prepare()["entries"]
    assert [entry["body"] for entry in entries[:2]] == ["hello", "legacy"]
    assert [entry["text"] for entry in entries[:2]] == ["You: hello", "You: legacy"]
    assert "本地时间" in path.read_text(encoding="utf-8")


def test_replay_enqueues_the_recorded_message_and_recovers_older_sprite_indices(replay):
    service, _, _, path = replay
    path.write_text(json.dumps([{"role": "assistant", "content": json.dumps({"dialog": [
        {"character_name": "Mio", "speech": "first", "sprite": 1},
        {"character_name": "Mio", "speech": "second", "sprite": 2},
        {"character_name": "Mio", "speech": "third", "sprite": -1},
    ]})}]), encoding="utf-8")
    recorder = ReplayRecorder(ReplayStore(path))
    recorder.record_message(PresentationMessage(
        audio_path="temporary.wav", name="Mio", text="Recorded caption",
        dialog_id="a" * 64, asset_id="3", effect="DISAPPOINTED",
    ))
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{'a' * 64}'>caption</p>"})
    snapshot = service.prepare()
    begin(service, snapshot, 1, 3)
    entries = service.plans[snapshot["id"]]["selected"]
    assert entries[0]["message"]["text"] == "Recorded caption"
    assert entries[0]["message"]["asset_id"] == "3"
    assert entries[0]["message"]["effect"] == "DISAPPOINTED"
    assert "audio_path" not in entries[0]["message"]
    assert [entry["message"]["asset_id"] for entry in entries[1:]] == ["2", "2"]


def test_range_is_inclusive_and_rejects_reversed_changed_and_outside_requests(replay):
    service, source, _, _ = replay
    snapshot = service.prepare()
    with pytest.raises(ValueError, match="终点"):
        begin(service, snapshot, 2, 1)
    begin(service, snapshot, 1, 1, True)
    assert service.plans[snapshot["id"]]["range"] == {snapshot["entries"][1]["key"]}
    with pytest.raises(ValueError, match="未启用"):
        service.generate(snapshot["id"], snapshot["entries"][2]["key"])
    service.cancel(snapshot["id"])
    next_snapshot = service.prepare()
    source[1]["text"] = "Mio: edited"
    with pytest.raises(ValueError, match="历史已改变"):
        begin(service, next_snapshot)


def test_generated_audio_survives_replay_and_is_reused_without_changing_archive_setting(replay, tmp_path):
    service, source, _, path = replay
    snapshot = service.prepare()
    begin(service, snapshot, 1, 2, True)
    key = snapshot["entries"][1]["key"]
    temporary = tmp_path / "generated.wav"
    temporary.write_bytes(b"RIFF-test-audio")
    synthesize = Mock(return_value=temporary)
    service._synthesize = synthesize
    voice = service.generate(snapshot["id"], key)
    assert voice["voiceSource"] == "generated"
    assert service.audio_source(snapshot["id"], key, 0).read_bytes() == b"RIFF-test-audio"
    assert service.generate(snapshot["id"], key) == voice
    assert synthesize.call_count == 1
    service.cancel(snapshot["id"])
    new = service.prepare()
    assert new["entries"][1]["voiceSource"] == "generated"
    assert new["entries"][1]["voiceUrls"]
    assert path.read_text() == "[]"
    assert "voiceId" not in source[1]
    assert not (path.parent / "audio" / "index.json").exists()


def test_available_original_voice_is_reused_even_when_fill_is_enabled(replay, tmp_path, monkeypatch):
    service, source, _, path = replay
    monkeypatch.chdir(tmp_path)
    cached = tmp_path / "cache" / "audio" / "original.wav"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"original")
    archive = VoiceArchive(path)
    archive.record("d" * 32, str(cached), dialog_id="a" * 64)
    archive.complete("d" * 32)
    archive.save_voice("d" * 32)
    cached.unlink()
    snapshot = service.prepare()
    begin(service, snapshot, 1, 1, True)
    service._synthesize = Mock(side_effect=AssertionError("do not replace original"))
    key = snapshot["entries"][1]["key"]
    assert service.generate(snapshot["id"], key)["voiceSource"] == "original"
    assert service.audio_source(snapshot["id"], key, 0).read_bytes() == b"original"


def test_start_requeues_only_the_selected_read_only_messages_and_reconnect_keeps_the_clip(replay):
    service, _, live, _ = replay
    live.update(dialogText="live line", characterName="Mio", options=["Live option"])
    snapshot = service.prepare()
    begin(service, snapshot, 1, 2)
    command = service.state.chat_stream.send_command.call_args.args[1]
    assert command["type"] == "replay-start"
    assert [e["key"] for e in command["payload"]["entries"]] == [e["key"] for e in snapshot["entries"][1:3]]
    assert command["payload"]["restore"]["dialogText"] == "live line"
    assert service.current(snapshot["id"])["snapshot"]["entries"] == snapshot["entries"][1:3]
    with pytest.raises(ValueError, match="退出当前回放"):
        service.prepare()
    with pytest.raises(ValueError, match="位置"):
        service.control(snapshot["id"], {"action": "seek", "index": 2})
    service.control(snapshot["id"], {"action": "seek", "index": 1})
    assert service.state.chat_stream.send_command.call_args.args[1]["payload"] == {
        "id": snapshot["id"], "action": "seek", "index": 1, "playing": False,
    }
    service.cancel(snapshot["id"])
    assert not service.is_active()


def test_choice_highlight_requires_a_unique_exact_next_reply(replay):
    service, source, _, _ = replay
    source[:] = [
        {"id": "choice", "role": "options", "text": "选项：向左/向右"},
        {"id": "answer", "role": "user", "text": "You: 向右"},
    ]
    selected = service.prepare()["entries"][0]
    assert selected["options"] == ["向左", "向右"] and selected["selectedIndex"] == 1
    source[1]["text"] = "You: 也许向右吧"
    assert service.prepare()["entries"][0]["selectedIndex"] is None
    source[0]["text"] = "选项：向右/向右"
    source[1]["text"] = "You: 向右"
    assert service.prepare()["entries"][0]["selectedIndex"] is None


def test_rolling_prefetch_pauses_and_reprioritizes_after_a_seek(replay):
    service, _, live, _ = replay
    snapshot = service.prepare()
    begin(service, snapshot, 1, 3, True)
    plan = service.plans[snapshot["id"]]
    keys = [e["key"] for e in snapshot["entries"][1:4]]
    live["replay"] = {"id": snapshot["id"], "index": 0, "paused": False}
    first_started, release_first, last_started = threading.Event(), threading.Event(), threading.Event()
    requested = []
    def generate(_plan_id, key):
        requested.append(key)
        if key == keys[0]:
            first_started.set()
            assert release_first.wait(2)
        if key == keys[-1]:
            last_started.set()
        plan["private"][key]["paths"] = [Path("cached.wav")]
        return {"voiceSource": "generated", "voiceLabel": "Mio"}
    service.generate = generate
    thread = threading.Thread(target=ChatReplayService._prefetch, args=(service, plan), daemon=True)
    thread.start()
    try:
        assert first_started.wait(2)
        live["replay"].update(index=2, paused=True)
        release_first.set()
        time.sleep(.15)
        assert requested == keys[:1]
        live["replay"]["paused"] = False
        assert last_started.wait(2)
        assert requested == [keys[0], keys[2]]
    finally:
        release_first.set()
        service.cancel(snapshot["id"])
        thread.join(2)
    assert not thread.is_alive()


def test_host_rejects_mutation_before_story_choice_or_transport(replay):
    from application.chat.host.commands import ChatCommandRouter
    service, _, _, _ = replay
    state = service.state
    state.chat_replay_service = service
    prepared = service.prepare()
    begin(service, prepared, 0, 1)
    mutate = Mock()
    router = ChatCommandRouter(Mock())
    router.register("submit-option", mutate)
    with pytest.raises(ValueError, match="回放期间"):
        router.handle(state, {"type": "submit-option", "payload": {"kind": "story-choice"}})
    mutate.assert_not_called()


@pytest.mark.parametrize(("translation", "language", "expected"), [
    ("", "zh", "你好"),
    ("（微笑）こんにちは", "ja", "こんにちは"),
])
def test_synthesis_uses_original_speech_and_keeps_the_shared_server_running(
    replay, tmp_path, monkeypatch, translation, language, expected,
):
    service, source, _, history_path = replay
    source[1]["text"] = "Mio: （微笑）你好"
    if translation:
        dialog = {"character_name": "Mio", "speech": "原始文本", "translate": translation}
        source[1]["dialogId"] = DialogIdentities("saved-turn").next(dialog)
        history_path.write_text(json.dumps([{
            "role": "assistant", CHAT_TURN_ID: "saved-turn", "content": json.dumps({"dialog": [dialog]}),
        }]), encoding="utf-8")
        store = ReplayStore(history_path)
        store.write(source[1]["dialogId"], "voice.json", {"fileKey": "d" * 64, "source": "generated"})
        store.path("d" * 64, "wav").write_bytes(b"audio generated from the old caption")
    snapshot = service.prepare()
    assert snapshot["entries"][1]["body"] == "（微笑）你好"
    assert not snapshot["entries"][1]["voiceUrls"]
    begin(service, snapshot, 1, 1, True)
    audio = tmp_path / "synthesized.wav"
    audio.write_bytes(b"audio")
    manager, adapter = Mock(), Mock()
    manager.generate_tts.return_value = str(audio)
    monkeypatch.setattr("ai.tts.tts_manager.TTSManager", Mock(return_value=manager))
    monkeypatch.setattr("ai.tts.tts_manager.TTSAdapterFactory.create_adapter", Mock(return_value=adapter))
    monkeypatch.setattr("ai.tts.model_session.tts_model_session", lambda *_: nullcontext())
    service.generate(snapshot["id"], snapshot["entries"][1]["key"])
    manager.set_language.assert_called_once_with(language)
    assert manager.generate_tts.call_args.args == (expected,)
    assert "text_processor" not in manager.generate_tts.call_args.kwargs
    manager.shutdown.assert_called_once_with(stop_server=False)


def test_cancellation_stops_new_requests_but_can_save_completed_audio(replay, tmp_path):
    service, _, _, _ = replay
    snapshot = service.prepare()
    begin(service, snapshot, 1, 2, True)
    def synthesize(*_):
        service.cancel(snapshot["id"])
        target = tmp_path / "completed.wav"
        target.write_bytes(b"completed")
        return target
    service._synthesize = Mock(side_effect=synthesize)
    key = snapshot["entries"][1]["key"]
    service.generate(snapshot["id"], key)
    with pytest.raises(ValueError, match="回放已结束"):
        service.generate(snapshot["id"], snapshot["entries"][2]["key"])
    assert service.prepare()["entries"][1]["voiceSource"] == "generated"


def test_replaced_session_rejects_late_generation_and_does_not_save(replay, tmp_path):
    service, _, _, path = replay
    snapshot = service.prepare()
    begin(service, snapshot, 1, 1, True)
    def synthesize(*_):
        target = tmp_path / "late.wav"
        target.write_bytes(b"late")
        service.state.chat_session["sessionId"] = "new-session"
        return target
    service._synthesize = synthesize
    with pytest.raises(ValueError, match="会话已改变"):
        service.generate(snapshot["id"], snapshot["entries"][1]["key"])
    assert not (path.parent / "replay").exists()
    assert not (tmp_path / "late.wav").exists()


@pytest.mark.parametrize("status", ["generating", "streaming", "speaking", "initializing"])
def test_busy_chat_cannot_start_replay(replay, status):
    service, _, state, _ = replay
    state["status"] = status
    with pytest.raises(ValueError, match="结束后"):
        service.prepare()


def test_recorder_saves_resolved_checkpoint_without_bridge_credentials(tmp_path):
    store = ReplayStore(tmp_path / "chat")
    recorder = ReplayRecorder(store)
    recorder.observe({"type": "background.change", "url": "http://localhost:123/api/media?path=night.png&shinsekai_bridge_token=secret"})
    recorder.observe({"type": "sprite.show", "slot": 0, "characterName": "Mio", "url": "mio.png"})
    recorder.observe({"type": "bgm.change", "url": "music.wav"})
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{'a' * 64}'>hello</p>"})
    frame = store.read("a" * 64, "frame.json")
    assert frame["backgroundPath"] == "/api/media?path=night.png"
    assert frame["sprites"][0]["path"] == "mio.png"
    assert frame["sprites"][0]["applyMode"] == "restore"
    assert "secret" not in store.path("a" * 64, "frame.json").read_text()
    recorder.observe({"type": "sprite.remove", "characterName": "Mio"})
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{'c' * 64}'>left</p>"})
    assert not store.read("c" * 64, "frame.json")["sprites"]
    recorder.observe({"type": "sprite.show", "slot": 0, "characterName": "Mio", "url": "mio.png"})
    recorder.observe({"type": "background.change", "url": "day.png"})
    recorder.observe({"type": "bgm.change", "url": ""})
    recorder.observe({"type": "dialog.end", "fullHtml": f"<p data-dialog-id='{'b' * 64}'>bye</p>"})
    frame = store.read("b" * 64, "frame.json")
    assert not frame["sprites"] and frame["bgmPath"] == ""


def test_conversation_cleanup_removes_only_owned_replay_files(tmp_path):
    path = tmp_path / "chat"
    store = ReplayStore(path)
    store.write("a" * 64, "frame.json", {"backgroundPath": "night.png"})
    store.path("b" * 64, "wav").write_bytes(b"audio")
    unrelated = store.directory / "my-recording.wav"
    unrelated.write_bytes(b"keep")
    remove_chat_history_storage(path)
    assert unrelated.read_bytes() == b"keep"
    assert not store.path("a" * 64, "frame.json").exists()
    assert not store.path("b" * 64, "wav").exists()
