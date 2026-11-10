from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat.presentation.replay import ReplayPresentation, ReplayPresentationMessage
from application.chat.presentation import updates
from application.chat.presentation.handlers import presentation
from application.chat.presentation.handlers.registry import UiOutputMessageDispatcher
from application.runtime.audio_playback_controller import VoicePlaybackController
from application.runtime.event_sink import fold_event_into_snapshot


def eventually(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def stage(monkeypatch):
    events, history, voices = [], ["live history"], []
    interrupt = threading.Event()
    backend = SimpleNamespace(
        start=lambda request, signal: (voices.append(request), signal(request.playback_id, "started", "")),
        stop=lambda request: None,
    )
    controller = VoicePlaybackController(backend, interrupt_event=interrupt)
    urls = SimpleNamespace(media_url=lambda url: "https://bridge" + url, avatar_url=Mock())
    ui = updates.StreamingUIUpdateManager(SimpleNamespace(emit=events.append), history, resource_urls=urls)
    runtime = SimpleNamespace(ui_update_manager=ui, ui_playback=SimpleNamespace(task_done_requested=interrupt))
    monkeypatch.setattr(presentation, "get_app_runtime", lambda: runtime)
    monkeypatch.setattr(presentation, "get_character_by_name", lambda name: None)
    dispatcher = UiOutputMessageDispatcher(presentation.get_ui_output_handlers())
    worker = SimpleNamespace(presentation_queue=Queue(), task_done_requested=interrupt,
                             playback_controller=controller, skip_speech=controller.interrupt,
                             ui_out_dispatcher=dispatcher)
    replay = ReplayPresentation(worker, ui)
    def consume():
        while True:
            item = worker.presentation_queue.get()
            try:
                if item is None:
                    return
                controller.prepare_next()
                replay.present(item)
            finally:
                worker.presentation_queue.task_done()
    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    yield replay, events, voices, history, controller
    if replay.active:
        replay.control({"id": "clip", "action": "stop"})
    worker.presentation_queue.put(None)
    thread.join(2)
    assert not thread.is_alive()


def entry(key, **extra):
    return {"key": key, "speaker": "Mio", "body": key, "paths": [], **extra}


def start(replay, entries):
    replay.start({"id": "clip", "entries": entries, "restore": {"dialogText": "live", "options": ["live choice"]}})


def test_queue_displays_historical_options_and_selection_without_writing_history(stage):
    replay, events, _, history, _ = stage
    start(replay, [entry("A/B", options=["A", "B"], selectedIndex=1)])
    eventually(lambda: replay.ended)
    assert history == ["live history"]
    assert next(e for e in events if e["type"] == "options.show") == {
        "type": "options.show", "options": ["A", "B"], "selectedIndex": 1,
    }
    assert not any(e["type"] == "history.replace" for e in events)


def test_replay_types_then_submits_the_user_message_before_the_reply(stage):
    replay, events, _, history, _ = stage
    start(replay, [
        entry("hello", role="user", speaker="You"),
        entry("answer", role="assistant", frame={"sprites": []}, waitForVoice=True),
    ])
    eventually(lambda: (replay.input or {}).get("phase") == "typing")
    replay.control({"id": "clip", "action": "pause"})
    time.sleep(.95)
    assert replay.input["phase"] == "typing"
    assert not any(event["type"] == "dialog.end" for event in events)
    replay.control({"id": "clip", "action": "play"})
    eventually(lambda: any("hello" in event.get("fullHtml", "") for event in events))
    submitted_at = time.monotonic()
    eventually(lambda: replay.waiting, timeout=4)
    assert time.monotonic() - submitted_at >= 2.25
    typing = next(i for i, event in enumerate(events) if (event.get("replay") or {}).get("input", {}).get("phase") == "typing")
    submit = next(i for i, event in enumerate(events) if (event.get("replay") or {}).get("input", {}).get("phase") == "submitting")
    user_line, reply = [i for i, event in enumerate(events) if event["type"] == "dialog.end"]
    assert typing < submit < user_line < reply
    assert events[user_line]["animate"] is False
    assert replay.input is None and history == ["live history"]


def test_seek_cancels_typing_before_the_old_user_message_is_submitted(stage):
    replay, events, _, history, _ = stage
    start(replay, [
        entry("old input", role="user", speaker="You"),
        entry("new target"),
    ])
    eventually(lambda: (replay.input or {}).get("phase") == "typing")
    replay.control({"id": "clip", "action": "seek", "index": 1})
    eventually(lambda: any("new target" in event.get("fullHtml", "") for event in events))
    assert not any("old input" in event.get("fullHtml", "") for event in events)
    assert replay.input is None and history == ["live history"]


def test_replay_keeps_the_stage_visible_when_the_next_user_message_is_typed(stage):
    replay, events, _, _, _ = stage
    start(replay, [
        entry("a", role="assistant", frame={"backgroundPath": "scene.png", "sprites": []}),
        entry("b", role="user", speaker="You"),
    ])
    eventually(lambda: (replay.input or {}).get("phase") == "typing")
    frames = [event["presentation"] for event in events if event["type"] == "presentation.restore"]
    assert frames[0]["backgroundPath"] == "scene.png"
    assert "backgroundPath" not in frames[1] and "sprites" not in frames[1]


def test_restores_available_historical_sprites_and_fills_missing_speakers(stage, tmp_path, monkeypatch):
    replay, events, _, _, _ = stage
    monkeypatch.chdir(tmp_path)
    for filename in ("current.png", "recorded.png", "other.png"):
        (tmp_path / filename).write_bytes(b"portrait")
    character = SimpleNamespace(name="Mio", color="#123456", sprites=[{"path": "removed.png"}, {"path": "current.png"}])
    monkeypatch.setattr(updates, "get_character_by_name", lambda name: character if name == "Mio" else None)
    monkeypatch.setattr(presentation, "get_character_by_name", lambda name: character if name == "Mio" else None)
    start(replay, [
        entry("old", role="assistant", message={"asset_id": "99"}),
        entry("saved", role="assistant", frame={"sprites": [{"id": "Mio", "path": "/api/media?path=recorded.png"}]}),
        entry("lost", role="assistant", frame={"sprites": [
            {"id": "Other", "path": "/api/media?path=other.png", "slot": 0},
            {"id": "Mio", "path": "/api/media?path=removed.png", "slot": 1},
        ]}),
        entry("cg", role="assistant", frame={"cgPath": "scene.png", "sprites": []}),
    ])
    eventually(lambda: sum(event["type"] == "presentation.restore" for event in events) == 4)
    frames = [event["presentation"]["sprites"] for event in events if event["type"] == "presentation.restore"]
    assert frames[0] == []
    assert frames[1] == [{"id": "Mio", "path": "https://bridge/api/media?path=recorded.png"}]
    assert frames[2] == [{"id": "Other", "path": "https://bridge/api/media?path=other.png", "slot": 0}]
    assert frames[3] == []
    assert [(event["url"], event["slot"]) for event in events if event["type"] == "sprite.show"] == [
        ("https://bridgecurrent.png", 0), ("https://bridgecurrent.png", 1),
    ]


def test_missing_voice_waits_then_uses_the_shared_audio_completion_contract(stage):
    replay, _, voices, _, controller = stage
    start(replay, [entry("a", waitForVoice=True)])
    eventually(lambda: replay.waiting)
    assert voices == []
    replay.voice({"id": "clip", "key": "a", "paths": ["archived.wav"]})
    eventually(lambda: len(voices) == 1)
    assert not replay.ended
    controller.handle_signal(voices[0].playback_id, "finished")
    eventually(lambda: replay.ended)


def test_legacy_sprite_instructions_change_the_pose_through_the_shared_handler(stage, monkeypatch, tmp_path):
    replay, events, _, history, _ = stage
    character = SimpleNamespace(name="Mio", color="#123456", sprites=[{"path": "first.png"}, {"path": "second.png"}])
    monkeypatch.chdir(tmp_path)
    for filename in ("first.png", "second.png"):
        (tmp_path / filename).write_bytes(b"portrait")
    monkeypatch.setattr(updates, "get_character_by_name", lambda name: character)
    monkeypatch.setattr(presentation, "get_character_by_name", lambda name: character)
    start(replay, [
        entry("a", role="assistant", message={"asset_id": "1"}),
        entry("b", role="assistant", message={"asset_id": "2", "text": "Recorded text"}),
    ])
    eventually(lambda: any(e.get("url") == "https://bridgesecond.png" for e in events))
    assert [event["url"] for event in events if event["type"] == "sprite.show"] == [
        "https://bridgefirst.png", "https://bridgesecond.png",
    ]
    eventually(lambda: any("Recorded text" in e.get("fullHtml", "") for e in events))
    assert history == ["live history"]


def test_pause_blocks_next_message_even_when_audio_finishes_or_arrives_late(stage):
    replay, events, voices, _, controller = stage
    start(replay, [entry("a", waitForVoice=True), entry("b")])
    eventually(lambda: replay.waiting)
    replay.control({"id": "clip", "action": "pause"})
    replay.voice({"id": "clip", "key": "a", "paths": ["a.wav"]})
    time.sleep(.08)
    assert voices == []
    replay.control({"id": "clip", "action": "play"})
    eventually(lambda: len(voices) == 1)
    replay.control({"id": "clip", "action": "pause"})
    controller.handle_signal(voices[0].playback_id, "finished")
    time.sleep(.08)
    assert replay.index == 0
    replay.control({"id": "clip", "action": "play"})
    eventually(lambda: replay.index == 1)


def test_seek_invalidates_queued_messages_and_late_voice_cannot_replace_target(stage):
    replay, events, voices, _, _ = stage
    start(replay, [entry("a", waitForVoice=True), entry("b"), entry("c")])
    eventually(lambda: replay.waiting)
    replay.control({"id": "clip", "action": "seek", "index": 2})
    eventually(lambda: any(e.get("fullHtml", "").endswith("：c</p>") for e in events))
    replay.voice({"id": "clip", "key": "a", "paths": ["late.wav"]})
    assert voices == []
    assert not any(e.get("fullHtml", "").endswith("：b</p>") for e in events)
    assert next(e for e in reversed(events) if e["type"] == "dialog.end")["animate"] is False
    replay.control({"id": "clip", "action": "play"})
    eventually(lambda: replay.ended)
    assert replay.index == 2


def test_exit_restores_live_presentation_and_drops_all_queued_and_late_items(stage):
    replay, events, voices, history, _ = stage
    start(replay, [entry("a", waitForVoice=True), entry("b")])
    eventually(lambda: replay.waiting)
    replay.control({"id": "clip", "action": "stop"})
    count = len(events)
    replay.voice({"id": "clip", "key": "a", "paths": ["late.wav"]})
    eventually(lambda: replay.worker.presentation_queue.unfinished_tasks == 0)
    assert len(events) == count
    assert voices == [] and history == ["live history"]
    assert events[-3]["presentation"] == {"dialogText": "live", "options": ["live choice"]}
    assert events[-1] == {"type": "replay.state", "replay": None}


def test_replay_snapshot_supports_reconnect_and_keeps_input_disabled_through_voice_events():
    snapshot = {"status": "idle", "options": []}
    progress = {"id": "clip", "index": 0, "total": 1, "paused": True, "ended": False, "waiting": False, "error": ""}
    snapshot = fold_event_into_snapshot(snapshot, {"type": "replay.state", "replay": progress})
    assert snapshot["status"] == "replaying" and snapshot["replay"] == progress
    snapshot = fold_event_into_snapshot(snapshot, {"type": "options.show", "options": ["A", "B"], "selectedIndex": 1})
    assert snapshot["replaySelectedIndex"] == 1


def test_normal_worker_consumes_replay_even_when_the_previous_live_turn_was_cancelled(monkeypatch):
    from application.runtime.workers import presentation_worker as module
    queue = Queue()
    events = []
    ui = SimpleNamespace(_emit=events.append)
    worker = object.__new__(module.PresentationWorker)
    worker.presentation_queue = queue
    worker.task_done_requested = threading.Event()
    worker.playback_controller = VoicePlaybackController(SimpleNamespace(), interrupt_event=worker.task_done_requested)
    worker.ui_update_manager = ui
    worker.ui_out_dispatcher = Mock()
    worker.dialog_channel = None
    worker.running = True
    worker._init_app = lambda: None
    worker.replay = ReplayPresentation(worker, ui)
    turn = SimpleNamespace(is_cancelled=lambda: True)
    runtime = SimpleNamespace(ui_playback=SimpleNamespace(playback_controller=worker.playback_controller),
                              chat_turn_service=SimpleNamespace(current_turn=lambda: turn), dialog_queue=Queue(),
                              presentation_queue=queue)
    monkeypatch.setattr(module, "get_app_runtime", lambda: runtime)
    start(worker.replay, [entry("archived")])
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    try:
        eventually(lambda: worker.replay.ended)
        worker.ui_out_dispatcher.dispatch.assert_called_once()
        assert worker.ui_out_dispatcher.dispatch.call_args.args[0].text == "archived"
        assert queue.unfinished_tasks == 0
    finally:
        worker.replay.control({"id": "clip", "action": "stop"})
        worker.running = False
        queue.put(None)
        thread.join(2)
    assert not thread.is_alive()
