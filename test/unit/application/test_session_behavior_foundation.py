"""Unit tests for SessionBehaviorCapability, CastingMap, CharacterMediaHandler, and Prefetch."""

from __future__ import annotations

from queue import Queue
from types import SimpleNamespace
import threading
import time
from typing import Any

from application.chat.presentation.handlers.dialog_media import CharacterMediaHandler
from application.runtime.workers.presentation_worker import PresentationWorker
from application.session_behavior import (
    BehaviorCommand,
    BehaviorOption,
    BehaviorStateEnvelope,
    BehaviorTransition,
    CastBinding,
    CastingMap,
    InteractionPolicy,
    SessionBehaviorCapability,
    SpeculativePrefetchCoordinator,
)
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import SqliteSessionStore
from sdk.hooks import BeforeCompactContext
from sdk.messages import LLMDialogMessage, PresentationMessage
from test.mocks import MockLLMAdapter


class _FakeBehavior:
    behavior_id = "demo_behavior"

    def __init__(self, casting: CastingMap | None = None) -> None:
        self._casting = casting
        self.restored_versions: list[int | None] = []
        self.command_calls = 0

    def describe_state(self, state, state_version: int) -> BehaviorStateEnvelope:
        return BehaviorStateEnvelope(
            behavior_id=self.behavior_id,
            state_version=state_version,
            stage_policy=InteractionPolicy(
                hide_input_layer=bool(state.get("hideInput", False)),
                playback_end_action="auto_advance",
                allow_free_text_interject=True,
                allow_unbound_speakers=True,
            ),
            hud={"cursor": state.get("cursor", 0)},
            options=(BehaviorOption(id="next", label="Next", action="advance"),),
            casting=self._casting.to_dict() if self._casting else {},
        )

    def handle_command(
        self,
        command: BehaviorCommand,
        *,
        state,
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition:
        self.command_calls += 1
        next_cursor = int(state.get("cursor", 0)) + 1
        return BehaviorTransition(
            next_state={**dict(state), "cursor": next_cursor},
            messages_to_commit=(
                {"role": "user", "source": "chunk_feed", "content": f"chunk {next_cursor}"},
            ),
            invalidate_prefetch=command.action == "jump",
        )

    def on_playback_idle(self, *, state, state_version: int, branch_id: str) -> BehaviorTransition | None:
        if state.get("autoNext"):
            return BehaviorTransition(
                next_state={**dict(state), "cursor": int(state.get("cursor", 0)) + 10, "autoNext": False}
            )
        return None

    def on_before_compact(self, context: BeforeCompactContext, *, state) -> None:
        context.add_instruction(f"Keep cursor={state.get('cursor', 0)}")

    def get_casting_map(self, state) -> CastingMap | None:
        return self._casting

    def on_state_restored(self, snapshot) -> None:
        self.restored_versions.append(snapshot.state_version if snapshot else None)


def test_casting_map_resolution_and_character_media_unbound_npc_passthrough(
    monkeypatch,
) -> None:
    casting = CastingMap(
        (CastBinding(character_name="Alice", aliases=("Miss A", "爱丽丝")),)
    )
    cc = SimpleNamespace(convert=lambda s: s.replace("愛麗絲", "爱丽丝"))
    assert casting.resolve("Alice") is not None
    assert casting.resolve("miss a") is not None
    assert casting.resolve("愛麗絲", cc=cc) is not None
    assert casting.resolve("Guard") is None
    assert casting.speaker_requires_media("Miss A") is True
    assert casting.speaker_requires_media("Guard") is False
    assert casting.bound_speaker_names() == ("Alice", "Miss A", "爱丽丝")

    pres_queue: Queue[PresentationMessage] = Queue()
    alice_cfg = SimpleNamespace(name="Alice", color="#ffffff", sprites=[{"path": "a.png"}], sprite_groups={})
    rt = SimpleNamespace(
        opencc=cc,
        config=SimpleNamespace(
            refresh_media_catalogs=lambda: None,
            get_character_by_name=lambda n: alice_cfg if n == "Alice" else None,
        ),
        presentation_queue=pres_queue,
        ui_update_manager=SimpleNamespace(post_busy_bar=lambda *_: None, hide_busy_bar=lambda: None),
        tts_manager=None,
        player_character="",
        read_player_speech=False,
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.character_media.get_app_runtime",
        lambda: rt,
    )

    tts_mock = SimpleNamespace(generate=lambda _req: ("voice.wav",))
    sprite_mock = SimpleNamespace(
        candidates=lambda _cfg: (),
        resolve=lambda _cfg, _cands, _req: SimpleNamespace(found=True, asset_id="0", voice_type="", voice_path="", voice_text=""),
    )
    handler = CharacterMediaHandler(
        tts_generation_strategy=tts_mock,
        sprite_resolver=sprite_mock,
        casting_map_provider=lambda: casting,
    )

    # Unbound NPC bypasses sprite lookup and TTS completely
    handler.handle(LLMDialogMessage(character_name="Shopkeeper", speech="Bread!", sprite="-1"))
    out_npc = pres_queue.get_nowait()
    assert out_npc.name == "Shopkeeper"
    assert out_npc.text == "Bread!"
    assert out_npc.audio_path == ""
    assert out_npc.asset_id == "-1"
    assert out_npc.is_system_message is False

    # Bound alias resolves canonical character config & uses TTS
    handler.handle(LLMDialogMessage(character_name="Miss A", speech="Hello", sprite="0"))
    out_alice = pres_queue.get_nowait()
    assert out_alice.name == "Alice"
    assert out_alice.audio_path == "voice.wav"


def test_capability_occ_idempotency_playback_idle_and_resync(tmp_path) -> None:
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    db_store = SqliteSessionStore(session_dir / "history.db")
    state_store = BehaviorStateStore(db_store, session_dir)
    events: list[dict[str, Any]] = []
    policy_calls: list[Any] = []
    llm_manager = SimpleNamespace(
        set_speaker_media_policy=lambda fn, bound: policy_calls.append((fn is not None, tuple(bound)))
    )
    casting = CastingMap((CastBinding(character_name="Alice"),))
    behavior = _FakeBehavior(casting=casting)
    cap = SessionBehaviorCapability(
        emit_event=events.append,
        llm_manager=llm_manager,
    )
    try:
        env = cap.attach_behavior(
            behavior,
            state_store=state_store,
            initial_state={"cursor": 0, "hideInput": True, "autoNext": True},
        )
        assert env.state_version == 1
        assert policy_calls[-1] == (True, ("Alice",))
        assert events[-1]["type"] == "behavior.state.replace"
        assert events[-1]["behavior"]["stagePolicy"]["hideInputLayer"] is True

        # 1. Valid command advances state_version 1 -> 2
        res = cap.handle_behavior_command(
            {"commandId": "cmd-1", "action": "advance", "expectedStateVersion": 1}
        )
        assert res.status == "accepted"
        assert res.envelope is not None and res.envelope.state_version == 2
        assert behavior.command_calls == 1

        # 2. Duplicate commandId is idempotent (no double execution!)
        dup = cap.handle_behavior_command(
            {"commandId": "cmd-1", "action": "advance", "expectedStateVersion": 1}
        )
        assert dup.status == "duplicate"
        assert behavior.command_calls == 1

        # 3. Stale expectedStateVersion triggers OCC rejection + resync event
        stale = cap.handle_behavior_command(
            {"commandId": "cmd-2", "action": "advance", "expectedStateVersion": 1}
        )
        assert stale.status == "stale_version"
        assert stale.envelope is not None and stale.envelope.state_version == 2
        assert events[-1]["behavior"]["stateVersion"] == 2

        # 4. playback_idle advances state_version 2 -> 3
        idle_env = cap.on_playback_idle()
        assert idle_env is not None and idle_env.state_version == 3

        # 5. History revert + mutation notification resyncs restored snapshot
        db_store.truncate_after(0, branch_id="main")
        resynced = cap.on_history_mutated("revert")
        assert resynced is not None and resynced.state_version == 1
        assert behavior.restored_versions[-1] == 1

        # 6. BeforeCompact injects instruction
        compact_ctx = BeforeCompactContext(messages=[], older_messages=[], recent_messages=[])
        cap.on_before_compact(compact_ctx)
        assert compact_ctx.extra_instructions == ["Keep cursor=0"]
    finally:
        db_store.close()


def test_speculative_prefetch_coordinator_isolation_and_max_inflight() -> None:
    fg_adapter = SimpleNamespace(cancel_called=0)
    fg_adapter.cancel = lambda: setattr(fg_adapter, "cancel_called", fg_adapter.cancel_called + 1)

    entered = threading.Event()
    release = threading.Event()
    created: list[Any] = []

    class _SlowPrefetchAdapter(MockLLMAdapter):
        def __init__(self, responses):
            super().__init__(responses=responses)
            self.cancelled = False

        def chat(self, messages, stream=False, **kwargs):
            if len(created) == 1:
                entered.set()
                release.wait(timeout=2.0)
            return super().chat(messages, stream=stream, **kwargs)

        def cancel(self):
            self.cancelled = True

    def factory():
        inst = _SlowPrefetchAdapter(
            ['{"dialog":[{"character_name":"Bob","speech":"Speculative line"}]}']
        )
        created.append(inst)
        return inst

    coordinator = SpeculativePrefetchCoordinator(create_prefetch_adapter=factory)
    try:
        h1 = coordinator.schedule(
            cache_key="chunk_00001",
            branch_id="main",
            state_version=1,
            messages=[{"role": "user", "content": "chunk 1"}],
            speaker_requires_media=lambda _n: False,
        )
        assert entered.wait(timeout=1.5)
        h2 = coordinator.schedule(
            cache_key="chunk_00002",
            branch_id="main",
            state_version=2,
            messages=[{"role": "user", "content": "chunk 2"}],
            speaker_requires_media=lambda _n: False,
        )
        assert h1.cancel_event.is_set()
        assert created[0].cancelled is True
        assert fg_adapter.cancel_called == 0
        release.set()

        assert h2.result(timeout=2.0) is not None
        # Wrong version misses cleanly
        assert coordinator.consume_if_valid("chunk_00002", branch_id="main", state_version=1) is None
        # Matching tuple consumes once
        hit = coordinator.consume_if_valid("chunk_00002", branch_id="main", state_version=2)
        assert hit is not None and hit.dialogs[0]["speech"] == "Speculative line"
        assert coordinator.consume_if_valid("chunk_00002", branch_id="main", state_version=2) is None
    finally:
        release.set()
        coordinator.shutdown()


def test_presentation_worker_fires_on_playback_idle_once(monkeypatch) -> None:
    fired: list[Any] = []
    worker = PresentationWorker(Queue(), on_playback_idle=fired.append)
    worker.ui_update_manager = SimpleNamespace(post_llm_reply_finished=lambda: None)

    turn = SimpleNamespace(
        is_cancelled=lambda: False,
        generation_complete=threading.Event(),
    )
    turn.generation_complete.set()
    mark_count = 0

    def _mark_idle(_t):
        nonlocal mark_count
        mark_count += 1
        return mark_count == 1

    rt = SimpleNamespace(
        dialog_queue=Queue(),
        presentation_queue=Queue(),
        ui_playback=SimpleNamespace(playback_controller=SimpleNamespace(is_active=lambda: False)),
        chat_turn_service=SimpleNamespace(mark_idle=_mark_idle),
    )
    monkeypatch.setattr("application.runtime.workers.presentation_worker.get_app_runtime", lambda: rt)

    assert worker._finish_turn_if_drained(turn) is True
    assert worker._finish_turn_if_drained(turn) is False
    assert fired == [turn]
