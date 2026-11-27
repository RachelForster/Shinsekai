"""Regression tests for Novel Theater casting guards, clear-history, prompt sync, and chapter jump isolation."""

from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
import threading
import time
from types import SimpleNamespace
from typing import Any

from application.novel_theater import (
    import_novel_document,
    materialize_novel_session_binding,
    prepare_novel_launch,
)
from application.session_behavior import SessionBehaviorCapability
from config.config_manager import ConfigManager
from config.schema import ApiConfig, AppConfig, SystemConfig
from core.chat_history.sqlite_session_store import close_all_session_stores
from core.chat_history.storage import (
    chat_history_active_path,
    chat_history_db_path,
    remove_chat_history_storage,
)
from core.messaging.chat_turn_service import ChatTurnService


def _dialog_json(speaker: str, text: str) -> str:
    return json.dumps(
        {
            "dialog": [
                {
                    "character_name": speaker,
                    "speech": text,
                    "sprite": "0",
                    "vibe": "calm",
                }
            ]
        },
        ensure_ascii=False,
    )


def _char(name: str, brief: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        color="#ffffff",
        character_brief=brief,
        personality="Steady",
        speaking_style="Clear",
        relationship="",
        sprites=[{"path": f"{name.lower()}.png"}],
        sprite_groups={},
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


def _setup_runtime(
    tmp_path: Path,
    monkeypatch,
    adapter: Any,
    *,
    turn_service: ChatTurnService | None = None,
):
    cfg = _isolated_config_manager()
    monkeypatch.setattr(cfg.config.system_config, "ui_language", "zh_CN")
    alice = _char("Alice", "First Heroine")
    bob = _char("Bob", "Second Companion")
    chars = {"Alice": alice, "Bob": bob}
    monkeypatch.setattr(cfg.config, "characters", [alice, bob])
    monkeypatch.setattr(cfg, "get_character_by_name", lambda name: chars.get(name))
    monkeypatch.setattr(cfg, "get_llm_api_config", lambda: ("Mock", "mock-model", "", "key"))
    monkeypatch.setattr(cfg, "merged_llm_factory_kwargs", lambda _p, base: base)
    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)

    hist_dir = tmp_path / "chat_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(hist_dir),
        config_manager=cfg,
        chat_session={},
    )
    novel_file = tmp_path / "control_story.txt"
    ch1 = "Chapter 1 Harbor\n\n" + ("Alice guarded the foggy harbor. " * 35)
    ch2 = "\n\nChapter 2 Citadel\n\n" + ("Bob scaled the high citadel wall. " * 35)
    novel_file.write_text(ch1 + ch2, encoding="utf-8")

    detail = import_novel_document(state, novel_file, title="Control Story")
    payload = prepare_novel_launch(
        state,
        {
            "docId": detail["manifest"]["docId"],
            "casting": [{"sourceName": "Alice", "aliases": [], "targetCharacter": "Alice"}],
        },
    )
    materialize_novel_session_binding(state, payload, payload["historyPath"])

    monkeypatch.setattr(
        "application.novel_theater.bootstrap.LLMAdapterFactory.create_adapter",
        lambda **_kwargs: adapter,
    )

    llm_messages: list[dict[str, Any]] = [{"role": "system", "content": "INITIAL SYSTEM"}]
    adapter_templates: list[str] = []
    history_obj = SimpleNamespace(
        messages=llm_messages,
        user_template="INITIAL SYSTEM",
        _seq_by_msg_id={},
        compact_manager=None,
    )
    llm_manager = SimpleNamespace(
        hook_dispatcher=None,
        generation_config={},
        user_template="INITIAL SYSTEM",
        llm_adapter=SimpleNamespace(set_user_template=adapter_templates.append),
        get_messages=lambda: list(llm_messages),
        _history=history_obj,
        set_speaker_media_policy=lambda *_args: None,
    )

    emitted: list[dict[str, Any]] = []
    dialog_queue: Queue[Any] = Queue()
    capability = SessionBehaviorCapability(
        emit_event=emitted.append,
        branch_id_provider=lambda: "main",
    )
    context = SimpleNamespace(
        args=SimpleNamespace(
            history=payload["historyPath"],
            media_selection_mode="indexed",
        ),
        config=cfg,
        startup=SimpleNamespace(llm_manager=llm_manager),
        runtime=SimpleNamespace(
            dialog_queue=dialog_queue,
            presentation_queue=Queue(),
            ui_worker=SimpleNamespace(set_on_playback_idle=lambda _cb: None),
            opencc=None,
        ),
        transport=None,
        ui_updates=None,
        chat_turn_service=turn_service or ChatTurnService(),
        app_runtime=None,
    )
    capability.configure_session_runtime(context)
    return (
        state,
        payload,
        capability,
        emitted,
        dialog_queue,
        llm_messages,
        history_obj,
        adapter_templates,
    )


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for condition")


def test_update_casting_rejected_while_generating_does_not_strand_phase(
    tmp_path: Path, monkeypatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    class _BlockingAdapter:
        def chat(self, messages, stream=False, **kwargs):
            del messages, stream, kwargs
            entered.set()
            release.wait(timeout=5.0)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=_dialog_json("Alice", "Beat complete."),
                            tool_calls=None,
                            reasoning_content=None,
                        )
                    )
                ]
            )

    _s, _p, capability, _emitted, _dq, _msgs, _hist, _tpls = _setup_runtime(
        tmp_path, monkeypatch, _BlockingAdapter()
    )
    try:
        capability.on_session_ready()
        assert entered.wait(timeout=3.0)

        snap_gen = capability.snapshot_payload()
        assert snap_gen is not None
        assert snap_gen["hud"]["phase"] == "generating"

        res = capability.handle_behavior_command(
            {
                "commandId": "cast-during-gen",
                "action": "update_casting",
                "expectedStateVersion": snap_gen["stateVersion"],
                "payload": {
                    "casting": {"bindings": []},
                    "castEntries": [],
                },
            }
        )
        assert res.status == "rejected"
        assert res.error_code == "behavior.busy"
        assert capability.snapshot_payload()["stateVersion"] == snap_gen["stateVersion"]

        release.set()
        _wait_until(
            lambda: (capability.snapshot_payload() or {}).get("hud", {}).get("phase")
            in {"playing", "ended"}
        )
    finally:
        release.set()
        capability.on_shutdown()
        close_all_session_stores()


def test_clear_history_reopens_behavior_store_and_allows_continued_play(
    tmp_path: Path, monkeypatch
) -> None:
    class _FastAdapter:
        def chat(self, messages, stream=False, **kwargs):
            del messages, stream, kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=_dialog_json("Alice", "Opening after clear."),
                            tool_calls=None,
                            reasoning_content=None,
                        )
                    )
                ]
            )

    _s, payload, capability, emitted, _dq, llm_messages, _hist, _tpls = _setup_runtime(
        tmp_path, monkeypatch, _FastAdapter()
    )
    history_path = payload["historyPath"]
    try:
        capability.on_session_ready()
        _wait_until(
            lambda: (capability.snapshot_payload() or {}).get("hud", {}).get("chunkIndex", 0)
            >= 1
        )
        old_store = capability.state_store

        # Simulate ChatCommandDispatcher._clear_history deleting history.db and closing store.
        remove_chat_history_storage(history_path)
        assert not chat_history_db_path(history_path).exists()

        emitted.clear()
        restored_env = capability.on_history_mutated("clear")
        assert restored_env is not None
        assert capability.state_store is not old_store
        assert chat_history_db_path(history_path).is_file()
        assert restored_env.hud["phase"] == "ready"
        assert restored_env.hud["chunkIndex"] == 0
        assert restored_env.casting["bindings"][0]["characterName"] == "Alice"
        assert any(ev.get("type") == "behavior.state.replace" for ev in emitted)

        # Subsequent commands work cleanly without sqlite3.ProgrammingError.
        adv = capability.handle_behavior_command(
            {
                "commandId": "adv-post-clear",
                "action": "advance",
                "expectedStateVersion": restored_env.state_version,
            }
        )
        assert adv.status == "accepted"
        _wait_until(
            lambda: (capability.snapshot_payload() or {}).get("hud", {}).get("chunkIndex", 0)
            >= 1
        )
    finally:
        capability.on_shutdown()
        close_all_session_stores()


def test_live_casting_update_refreshes_prompt_and_jump_isolates_audio_and_history(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[list[dict[str, Any]]] = []

    class _RecordingAdapter:
        def chat(self, messages, stream=False, **kwargs):
            del stream, kwargs
            calls.append(list(messages))
            last = str(messages[-1].get("content") or "") if messages else ""
            if "Chapter 2 Citadel" in last:
                text = _dialog_json("Bob", "Chapter two secret plot event.")
            elif "Chapter 1 Harbor" in last and len(calls) > 1:
                text = _dialog_json("Bob", "Replayed harbor with Bob.")
            else:
                text = _dialog_json("Alice", "Chapter one beat.")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=text, tool_calls=None, reasoning_content=None
                        )
                    )
                ]
            )

    interrupted_events: list[str] = []
    buffered_queue: Queue[str] = Queue()
    buffered_queue.put("stale-audio-item")

    turn_service = ChatTurnService(
        stop_playback=lambda: interrupted_events.append("stop_playback"),
        clear_pending=(lambda: buffered_queue.get_nowait() if not buffered_queue.empty() else None,),
    )

    (
        _state,
        payload,
        capability,
        _emitted,
        dialog_queue,
        llm_messages,
        history_obj,
        adapter_templates,
    ) = _setup_runtime(tmp_path, monkeypatch, _RecordingAdapter(), turn_service=turn_service)
    history_path = payload["historyPath"]

    try:
        # 1. Play Chapter 1 opening beat
        capability.on_session_ready()
        _wait_until(
            lambda: (capability.snapshot_payload() or {}).get("hud", {}).get("phase")
            in {"playing", "ended"}
            and not dialog_queue.empty()
        )
        dialog_queue.get_nowait()
        assert len(llm_messages) == 3  # [system, user, assistant]

        # 2. Live update_casting -> Bob updates LLM system prompt, user_template, and SQLite
        snap1 = capability.snapshot_payload()
        assert snap1 is not None
        cast_res = capability.handle_behavior_command(
            {
                "commandId": "recast-bob",
                "action": "update_casting",
                "expectedStateVersion": snap1["stateVersion"],
                "payload": {
                    "casting": {
                        "bindings": [
                            {"characterName": "Bob", "aliases": ["Bobby"], "role": "protagonist"}
                        ]
                    },
                    "castEntries": [
                        {
                            "sourceName": "Bobby",
                            "aliases": [],
                            "targetCharacter": "Bob",
                            "role": "protagonist",
                        }
                    ],
                },
            }
        )
        assert cast_res.status == "accepted"
        assert "Bob" in llm_messages[0]["content"]
        assert "Bobby" in llm_messages[0]["content"]
        assert history_obj.user_template == llm_messages[0]["content"]
        assert adapter_templates[-1] == llm_messages[0]["content"]
        assert (
            capability.state_store._session_store.get_system_prompt(branch_id="main")
            == llm_messages[0]["content"]
        )
        active_disk = json.loads(chat_history_active_path(history_path).read_text(encoding="utf-8"))
        assert active_disk[0]["content"] == llm_messages[0]["content"]

        # 3. Jump to Chapter 2 -> interrupts audio/playback and isolates prior turns
        calls.clear()
        interrupted_events.clear()
        snap2 = capability.snapshot_payload()
        assert snap2 is not None
        jump2 = capability.handle_behavior_command(
            {
                "commandId": "jump-ch2",
                "action": "jump_chapter",
                "expectedStateVersion": snap2["stateVersion"],
                "payload": {"chapterIndex": 1},
            }
        )
        assert jump2.status == "accepted"
        assert "stop_playback" in interrupted_events
        assert buffered_queue.empty()
        _wait_until(lambda: not dialog_queue.empty())
        dialog_queue.get_nowait()

        # Jump beat must NOT have carried old Chapter 1 turns into the request
        ch2_calls = [
            c for c in calls if "Chapter 2 Citadel" in str(c[-1].get("content") or "")
        ]
        assert len(ch2_calls) == 1
        assert len(ch2_calls[0]) == 2  # [updated system prompt, chapter 2 feed]
        assert "Chapter one beat." not in json.dumps(ch2_calls[0], ensure_ascii=False)

        # 4. Jump BACK to Chapter 1 -> Chapter 2's future plot must NOT leak into Chapter 1
        _wait_until(
            lambda: (capability.snapshot_payload() or {}).get("hud", {}).get("phase")
            in {"playing", "ended"}
        )
        calls.clear()
        snap3 = capability.snapshot_payload()
        assert snap3 is not None
        jump1 = capability.handle_behavior_command(
            {
                "commandId": "jump-ch1",
                "action": "jump_chapter",
                "expectedStateVersion": snap3["stateVersion"],
                "payload": {"chapterIndex": 0},
            }
        )
        assert jump1.status == "accepted"
        _wait_until(lambda: not dialog_queue.empty())
        dialog_queue.get_nowait()

        ch1_calls = [
            c for c in calls if "Chapter 1 Harbor" in str(c[-1].get("content") or "")
        ]
        assert len(ch1_calls) == 1
        assert len(ch1_calls[0]) == 2  # Only system prompt + jumped chapter 1 prompt
        serialized_req = json.dumps(ch1_calls[0], ensure_ascii=False)
        assert "Chapter two secret plot event." not in serialized_req
        assert "Bob" in ch1_calls[0][0]["content"]

        _wait_until(
            lambda: (capability.snapshot_payload() or {}).get("hud", {}).get("phase")
            in {"playing", "ended"}
        )
        # SQLite turns table should also contain only the clean post-jump beat turns
        turns = list(capability.state_store._session_store.list_turns(branch_id="main"))
        assert len(turns) == 2
    finally:
        capability.on_shutdown()
        close_all_session_stores()
