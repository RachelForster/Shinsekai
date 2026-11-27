"""Unit tests for NovelTheaterBehavior runtime loop, auto-attach, OCC, prefetch, and playback."""

from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
import threading
import time
from types import SimpleNamespace
from typing import Any

from application.chat.presentation.handlers.dialog_media import CharacterMediaHandler
from application.novel_theater import (
    import_novel_document,
    materialize_novel_session_binding,
    prepare_novel_launch,
)
from application.novel_theater.behavior import NovelTheaterBehavior
from application.novel_theater.turn_runner import NovelTheaterTurnRunner
from application.runtime.workers.presentation_worker import PresentationWorker
from application.session_behavior import (
    CastingMap,
    SessionBehaviorCapability,
    SpeculativePrefetchCoordinator,
)
from config.config_manager import ConfigManager
from config.schema import ApiConfig, AppConfig, SystemConfig
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import close_all_session_stores
from core.chat_history.storage import (
    chat_history_active_path,
    chat_history_session_dir,
    open_session_store,
)
from core.document import DocumentRepository
from core.messaging.chat_turn_service import ChatTurnService
from core.storage.layout import StorageLayout
from sdk.hooks import BeforeCompactContext
from sdk.messages import PresentationMessage
from test.mocks import MockLLMAdapter


def _dialog_json(speaker: str, text: str, *, sprite: str = "0") -> str:
    return json.dumps(
        {
            "dialog": [
                {
                    "character_name": speaker,
                    "speech": text,
                    "sprite": sprite,
                    "vibe": "calm",
                }
            ]
        },
        ensure_ascii=False,
    )


def _isolated_config_manager() -> ConfigManager:
    cfg = object.__new__(ConfigManager)
    cfg._config = AppConfig(
        characters=[],
        background_list=[],
        api_config=ApiConfig(),
        system_config=SystemConfig(ui_language="zh_CN"),
    )
    cfg._characters_revision = ""
    cfg._API_CONFIG_PATH = Path("nonexistent-test-api.yaml")
    return cfg


def _setup_project_and_doc(tmp_path: Path, monkeypatch):
    cfg = _isolated_config_manager()
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)
    alice = SimpleNamespace(
        name="Alice",
        color="#ffffff",
        character_brief="Heroine",
        personality="",
        speaking_style="",
        relationship="",
        sprites=[{"path": "alice.png"}],
        sprite_groups={},
    )
    cfg.config.characters = [alice]
    cfg.get_character_by_name = lambda n: alice if n == "Alice" else None
    hist_dir = tmp_path / "chat_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(hist_dir),
        config_manager=cfg,
        chat_session={},
    )
    novel_file = tmp_path / "story.txt"
    ch1 = "Chapter 1 Arrival\n\n" + ("Alice walked through the lantern hall. " * 45)
    ch2 = "\n\nChapter 2 Departure\n\n" + ("Unbound Narrator watched the train leave. " * 45)
    novel_file.write_text(ch1 + ch2, encoding="utf-8")
    detail = import_novel_document(state, novel_file, title="Lantern Story")
    doc_id = detail["manifest"]["docId"]
    payload = prepare_novel_launch(
        state,
        {
            "docId": doc_id,
            "casting": [{"sourceName": "Alice", "aliases": [], "targetCharacter": "Alice"}],
        },
    )
    materialize_novel_session_binding(state, payload, payload["historyPath"])
    return state, cfg, detail, payload


def test_auto_attach_kickoff_monotonic_events_prefetch_and_chapter_jump(
    tmp_path: Path, monkeypatch
) -> None:
    state, cfg, detail, payload = _setup_project_and_doc(tmp_path, monkeypatch)
    history_path = payload["historyPath"]

    emitted: list[dict[str, Any]] = []
    emitted_event = threading.Event()
    dialog_queue: Queue[Any] = Queue()
    pres_queue: Queue[PresentationMessage] = Queue()
    turn_service = ChatTurnService()

    cfg.get_llm_api_config = lambda: ("Mock", "mock-model", "", "key")
    cfg.merged_llm_factory_kwargs = lambda _p, base: base

    class _ScriptedNovelAdapter:
        def __init__(self) -> None:
            self.call_history: list[dict[str, Any]] = []

        def chat(self, messages, stream=False, **kwargs):
            self.call_history.append({"messages": messages, "stream": stream, "kwargs": kwargs})
            last = str(messages[-1].get("content") or "") if messages else ""
            meta = last.split("\n\n", 1)[0]
            if "Chapter 2 Departure" in meta:
                text = _dialog_json("Guard", "Unbound chapter jump beat.")
            elif "2/4" in meta:
                text = _dialog_json("Alice", "Beat one prefetched.")
            else:
                text = _dialog_json("Alice", "Beat zero opening.")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=text, tool_calls=None, reasoning_content=None
                        )
                    )
                ]
            )

    adapter = _ScriptedNovelAdapter()
    monkeypatch.setattr(
        "application.novel_theater.bootstrap.LLMAdapterFactory.create_adapter",
        lambda **_kwargs: adapter,
    )

    llm_messages: list[dict[str, Any]] = []
    llm_manager = SimpleNamespace(
        hook_dispatcher=None,
        generation_config={},
        get_messages=lambda: list(llm_messages),
        _history=SimpleNamespace(messages=llm_messages, _seq_by_msg_id={}, compact_manager=None),
        set_speaker_media_policy=lambda *_args: None,
    )

    capability = SessionBehaviorCapability(
        emit_event=lambda ev: (emitted.append(ev), emitted_event.set()),
        branch_id_provider=lambda: "main",
    )
    runtime = SimpleNamespace(
        dialog_queue=dialog_queue,
        presentation_queue=pres_queue,
        ui_worker=SimpleNamespace(set_on_playback_idle=lambda _cb: None),
        opencc=None,
    )
    context = SimpleNamespace(
        args=SimpleNamespace(history=history_path, media_selection_mode="indexed"),
        config=cfg,
        startup=SimpleNamespace(llm_manager=llm_manager),
        runtime=runtime,
        transport=None,
        ui_updates=None,
        chat_turn_service=turn_service,
        app_runtime=None,
    )

    capability.configure_session_runtime(context)
    assert isinstance(capability.behavior, NovelTheaterBehavior)

    # Fresh session kickoff on ready -> emitting generating (v2) then playing chunk 1 (v3)
    capability.on_session_ready()

    deadline = time.monotonic() + 5.0
    playing_versions: list[int] = []
    while time.monotonic() < deadline:
        replaces = [
            e["behavior"]
            for e in emitted
            if e.get("type") == "behavior.state.replace" and e.get("behavior") is not None
        ]
        versions = [int(b["stateVersion"]) for b in replaces]
        assert versions == sorted(versions), f"Non-monotonic versions: {versions}"
        playing = [
            b
            for b in replaces
            if b.get("hud", {}).get("phase") == "playing"
            and int(b.get("hud", {}).get("chunkIndex", 0)) >= 1
        ]
        if playing and not dialog_queue.empty():
            playing_versions = [int(b["stateVersion"]) for b in playing]
            break
        time.sleep(0.02)

    assert playing_versions, f"Beat 0 never reached playing state; emitted={emitted}"
    d0 = dialog_queue.get(timeout=1.0)
    assert d0.name == "Alice"
    assert d0.text == "Beat zero opening."

    # Verify PresentationWorker triggers on_playback_idle which schedules speculative prefetch
    capability.on_playback_idle(None)
    turn_runner = capability.behavior._turn_runner
    assert isinstance(turn_runner, NovelTheaterTurnRunner)
    prefetch = turn_runner._prefetch
    prefetched_chunk = turn_runner._chunks[1]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        # peek via handle completion
        time.sleep(0.02)
        if len(adapter.call_history) >= 2:
            # Ensure prefetch worker finished storing result
            handle = prefetch._active_handle
            if handle is None or handle.future.done():
                break

    # Advance should consume prefetched beat synchronously and deliver STRICTLY after replace emit
    ver_before_advance = playing_versions[-1]
    res = capability.handle_behavior_command(
        {
            "commandId": "adv-1",
            "action": "advance",
            "expectedStateVersion": ver_before_advance,
        }
    )
    assert res.status == "accepted"
    assert res.envelope is not None
    assert res.envelope.hud["chunkIndex"] == 2
    d1 = dialog_queue.get(timeout=1.0)
    assert d1.text == "Beat one prefetched."

    # Test jump_chapter (chapter 1 = Chapter 2) invalidates prefetch and commits beat for chapter 2
    ver_before_jump = res.envelope.state_version
    total_chapters = len(detail["chapters"])
    assert total_chapters >= 2
    jump_res = capability.handle_behavior_command(
        {
            "commandId": "jump-2",
            "action": "jump_chapter",
            "expectedStateVersion": ver_before_jump,
            "payload": {"chapterIndex": 1},
        }
    )
    assert jump_res.status == "accepted"

    deadline = time.monotonic() + 5.0
    jumped_msg = None
    while time.monotonic() < deadline:
        if not dialog_queue.empty():
            jumped_msg = dialog_queue.get(timeout=0.5)
            break
        time.sleep(0.02)
    assert jumped_msg is not None
    assert jumped_msg.name == "Guard"
    assert jumped_msg.text == "Unbound chapter jump beat."

    # Verify CharacterMediaHandler emits pure-text without media for unbound Guard
    pres_out: Queue[PresentationMessage] = Queue()
    media_rt = SimpleNamespace(
        opencc=None,
        config=cfg,
        presentation_queue=pres_out,
        ui_update_manager=SimpleNamespace(post_busy_bar=lambda *_: None, hide_busy_bar=lambda: None),
        tts_manager=None,
        player_character="",
        read_player_speech=False,
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.character_media.get_app_runtime",
        lambda: media_rt,
    )
    handler = CharacterMediaHandler(casting_map_provider=capability._active_casting_map)
    handler.handle(jumped_msg)
    pres_msg = pres_out.get_nowait()
    assert pres_msg.audio_path == ""
    assert pres_msg.asset_id == "-1"
    assert pres_msg.text == "Unbound chapter jump beat."

    # Verify on_before_compact injects cast summary instruction
    compact_ctx = BeforeCompactContext(
        messages=[], older_messages=[], recent_messages=[]
    )
    capability.on_before_compact(compact_ctx)
    assert any("Alice" in instr for instr in compact_ctx.extra_instructions)

    capability.on_shutdown()
    close_all_session_stores()


def test_crash_recovery_resets_generating_phase_on_reattach(tmp_path: Path, monkeypatch) -> None:
    state, cfg, _detail, payload = _setup_project_and_doc(tmp_path, monkeypatch)
    history_path = payload["historyPath"]
    session_dir = chat_history_session_dir(history_path)

    store = open_session_store(history_path)
    bstore = BehaviorStateStore(store, session_dir)
    latest = bstore.get_latest_state("main")
    assert latest is not None
    bstore.commit_behavior_turn(
        branch_id="main",
        behavior_id="novel_theater",
        expected_state_version=latest.state_version,
        next_state={**latest.state, "phase": "generating", "lastError": ""},
        messages=(),
    )

    emitted: list[dict[str, Any]] = []
    capability = SessionBehaviorCapability(
        emit_event=emitted.append,
        branch_id_provider=lambda: "main",
    )
    context = SimpleNamespace(
        args=SimpleNamespace(history=history_path, media_selection_mode="indexed"),
        config=cfg,
        startup=SimpleNamespace(llm_manager=None),
        runtime=None,
        transport=None,
        ui_updates=None,
        chat_turn_service=None,
        app_runtime=None,
    )
    capability.configure_session_runtime(context)
    snap = capability.snapshot_payload()
    assert snap is not None
    assert snap["hud"]["phase"] == "ready"

    capability.on_shutdown()
    close_all_session_stores()
