"""End-to-end integration tests for non-destructive Auto-Compact and 4-in-1 revert/reroll cascade."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai.llm.history_manager import HistoryManager
from ai.llm.llm_manager import LLMManager
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.engine import HybridMemoryEngine
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.queue import MemoryWriteQueue
import ai.memory.runtime as memory_runtime
from application.chat.history.state import (
    pop_last_assistant_turn_payload,
    revert_chat_history,
)
from core.chat_history.models import (
    OutfitState,
    is_compact_summary_message,
    render_messages_to_ui_history,
)
from core.chat_history.sqlite_session_store import (
    close_all_session_stores,
    set_default_shared_memory_rollback,
)
from core.chat_history.storage import (
    chat_history_active_path,
    open_session_store,
)
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from frontend_bridge_core.routes.memory_routes import MEMORY_ROUTES
from frontend_bridge_core.routes.router import ApiRequest
from sdk.adapters.memory import MemoryScopeFilter
from sdk.hooks import PluginHookDispatcher


def _dialog_json(character: str, speech: str, sprite: str = "1") -> str:
    return json.dumps(
        {
            "dialog": [
                {
                    "character_name": character,
                    "sprite": sprite,
                    "speech": speech,
                }
            ]
        },
        ensure_ascii=False,
    )


class _FakeRoleplayAndCompactionAdapter:
    """Deterministic LLM adapter serving compaction summaries and memory extraction JSON."""

    def __init__(self) -> None:
        self.compact_calls: list[str] = []
        self.extract_calls: list[str] = []
        self.user_template: str = ""

    def set_user_template(self, template: str) -> None:
        self.user_template = template

    def chat(self, messages: list[dict[str, Any]], stream: bool = False, **kwargs: Any) -> Any:
        sys_text = str(messages[0].get("content") or "") if messages else ""
        user_text = str(messages[-1].get("content") or "") if messages else ""
        if "对话总结助手" in sys_text or "压缩成一个简洁的总结" in user_text:
            self.compact_calls.append(user_text)
            idx = len(self.compact_calls)
            text = f"阶段总结#{idx}：已记录前序约会行程（共第{idx}次压缩）。"
            return SimpleNamespace(content=text, text=text)

        if (
            "extract durable long-term memories" in sys_text.lower()
            or "长期记忆" in sys_text
            or "長期記憶" in sys_text
            or "Return JSON array only" in user_text
            or "仅返回 JSON 数组" in user_text
        ):
            self.extract_calls.append(user_text)
            distinct_facts = [
                "压缩归档事实Alpha：Mio清晨在站前广场挥手迎接用户",
                "压缩归档事实Beta：两人在深海展区观看了发光水母群",
                "压缩归档事实Gamma：午餐时分在露台点了一份海鲜意面",
                "压缩归档事实Delta：黄昏时在旧书店挑选了一本诗集",
                "压缩归档事实Epsilon：入夜后在港口吹着海风散步",
            ]
            fact = distinct_facts[(len(self.extract_calls) - 1) % len(distinct_facts)]
            extracted = json.dumps(
                [
                    {
                        "character_name": "Mio",
                        "memory": fact,
                        "confidence": 0.92,
                    }
                ],
                ensure_ascii=False,
            )
            return SimpleNamespace(content=extracted, text=extracted)

        reply = _dialog_json("Mio", "好的！")
        return SimpleNamespace(content=reply, text=reply)

    def decode_response(self, response: Any) -> Any:
        return SimpleNamespace(content=str(getattr(response, "content", "") or ""))


@pytest.fixture()
def isolated_hybrid_memory_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bind ai.memory.runtime to an isolated ONNX-free HybridMemoryEngine for testing."""
    shared_db = SqliteHybridStore(tmp_path / "global_shinsekai_store.db")
    engine = HybridMemoryEngine(
        embedder=DeterministicHashEmbedder(dimensions=32),
        repo=shared_db,
        vector_store=shared_db,
        store=shared_db,
    )
    monkeypatch.setattr(memory_runtime, "_mem0", engine)
    monkeypatch.setattr(memory_runtime, "_mem0_loading", False)
    monkeypatch.setattr(memory_runtime, "_mem0_load_error", None)
    try:
        yield engine, shared_db
    finally:
        set_default_shared_memory_rollback(None)
        close_all_session_stores()
        shared_db.close()


def test_multi_auto_compact_before_compact_extraction_restart_and_four_in_one_revert_cascade(
    tmp_path: Path,
    isolated_hybrid_memory_runtime: tuple[HybridMemoryEngine, SqliteHybridStore],
) -> None:
    engine, shared_db = isolated_hybrid_memory_runtime
    session_dir = tmp_path / "chat_history" / "mio-date-session"
    active_file = chat_history_active_path(session_dir)

    adapter = _FakeRoleplayAndCompactionAdapter()
    dispatcher = PluginHookDispatcher()

    from ai.memory.operations import memory_remember, memory_rollback_count

    write_queue = MemoryWriteQueue(remember_func=memory_remember)
    hooks = MemoryAutoHooks(
        llm_adapter=adapter,
        character_names=["Mio"],
        queue=write_queue,
        extract_interval_turns=99,  # Ensure extraction is driven specifically by BEFORE_COMPACT!
    )
    hooks.register(dispatcher)

    def _shared_rollback(sid: str, cutoff_seq: int) -> int:
        pending = hooks.rollback_after_turn(sid, cutoff_seq)
        return pending + memory_rollback_count(sid, cutoff_seq)

    set_default_shared_memory_rollback(_shared_rollback)

    # max_tokens=520 keeps Turn 1 uncompacted, then triggers 2+ Auto-Compacts across Turns 2..5.
    llm = LLMManager(
        adapter=adapter,
        user_template="你是温柔的女主角Mio。",
        max_tokens=520,
        compact_threshold=0.45,
        compact_target_ratio=0.35,
        history_recent_messages=2,
        history_file=str(active_file),
        hook_dispatcher=dispatcher,
        tools_enabled=False,
    )
    llm.set_user_template("你是温柔的女主角Mio。")

    store = open_session_store(session_dir)
    sid = store.session_id
    ui_history: list[str] = []

    def _run_turn(
        user_text: str,
        mio_speech: str,
        *,
        outfit: str,
        location_slot: str,
    ) -> tuple[int, int]:
        llm.add_message(
            "user",
            f"{user_text}（补充场景描写以推进上下文窗口长度：{user_text * 3}）",
            display_content=user_text,
            input_text=user_text,
        )
        u_seq = store.list_turns()[-1].seq
        store.set_outfit_state(OutfitState("Mio", outfit))
        memory_remember(
            f"Mio与用户在{location_slot}",
            character_name="Mio",
            slot_key="Mio:location",
            source_session_id=sid,
            source_turn_seq=u_seq,
        )

        assistant_payload = _dialog_json(
            "Mio",
            f"{mio_speech}（Mio细致地回应着当前的氛围：{mio_speech * 3}）",
        )
        llm.add_message("assistant", assistant_payload)
        a_seq = store.list_turns()[-1].seq
        return u_seq, a_seq

    # Drive 5 full turns -> triggers 2+ automatic compactions!
    _run_turn("我们在车站集合吧", "好呀，我已经到检票口啦！", outfit="uniform", location_slot="车站")
    _run_turn("现在一起去水族馆看海豚", "海豚表演太精彩啦！", outfit="uniform", location_slot="水族馆")
    _run_turn("中午换上约会连衣裙去海景餐厅", "这件连衣裙好看吗？", outfit="date_dress", location_slot="海景餐厅")
    _run_turn("下午去商店街买可丽饼", "草莓奶油味超甜！", outfit="date_dress", location_slot="商店街")
    _run_turn("晚上披上夜行外套坐摩天轮", "夜景好美呀，不想回家。", outfit="night_coat", location_slot="摩天轮")

    # Add a pinned memory on the final turn that MUST survive any rollback.
    memory_remember(
        "Mio最喜欢的甜点是草莓可丽饼",
        character_name="Mio",
        source_session_id=sid,
        source_turn_seq=10,
    )
    all_mio_memories = shared_db.list_by_scope(MemoryScopeFilter(owner_ids=("Mio",)))
    pinned_target = next(r for r in all_mio_memories if "草莓可丽饼" in r.detail_text)
    shared_db.set_pinned(pinned_target.id, True)

    # 1. Verify multiple Auto-Compacts happened AND BEFORE_COMPACT extracted memories first!
    checkpoints = list(store.list_compact_checkpoints())
    assert len(checkpoints) >= 2
    assert len(adapter.compact_calls) >= 2
    assert len(adapter.extract_calls) >= 2

    extracted_memories = [
        r for r in shared_db.list_by_scope(MemoryScopeFilter(owner_ids=("Mio",)))
        if "压缩归档事实" in r.detail_text
    ]
    assert len(extracted_memories) >= 2
    for rec in extracted_memories:
        assert rec.source_session_id == sid
        assert rec.source_turn_seq is not None and rec.source_turn_seq > 0

    # 2. Verify Non-Destructive invariant: SQLite retains all 10 raw turns while LLM window is compacted!
    assert len(store.list_turns()) == 10
    active_window = llm.get_messages()
    assert len(active_window) < 10
    assert any(is_compact_summary_message(m) for m in active_window)

    # 3. Save & simulate full application restart: UI gets 100% of 10 turns, LLM gets active checkpoint window!
    hm = HistoryManager(ui_history)
    assert hm.save_chat_history(str(active_file), llm.get_messages()) is True
    HistoryManager.delete_tmp(str(active_file))

    mirrored_json = json.loads(active_file.read_text(encoding="utf-8"))
    # Mirror has system + all 10 raw turns (no lossy summary overwriting active.json!)
    assert len(mirrored_json) == 11
    assert not any(is_compact_summary_message(m) for m in mirrored_json)

    reloaded_ui: list[str] = []
    hm_reloaded = HistoryManager(reloaded_ui)
    loaded_full = hm_reloaded.load_chat_history(str(active_file))
    assert len(loaded_full) == 11
    assert len(reloaded_ui) == 10  # All 5 user + 5 assistant rows visible in UI!

    llm_restarted = LLMManager(
        adapter=adapter,
        user_template="你是温柔的女主角Mio。",
        max_tokens=520,
        compact_threshold=0.45,
        compact_target_ratio=0.35,
        history_recent_messages=2,
        history_file=str(active_file),
        hook_dispatcher=dispatcher,
        tools_enabled=False,
    )
    llm_restarted.set_messages(loaded_full)
    restarted_window = llm_restarted.get_messages()
    assert any(is_compact_summary_message(m) for m in restarted_window)
    assert len(restarted_window) < 11

    # 4. Test Reroll on latest turn (Turn 5 "摩天轮", seq 9-10 -> truncates after seq 8):
    reroll_payload = pop_last_assistant_turn_payload(
        reloaded_ui,
        restarted_window,
        llm_manager=llm_restarted,
        history_path=str(session_dir),
    )
    assert reroll_payload["text"] == "晚上披上夜行外套坐摩天轮"
    assert len(reloaded_ui) == 8
    assert len(store.list_turns()) == 8
    assert store.get_outfit_state("Mio") == OutfitState(
        character_name="Mio",
        active_group="date_dress",
        locked=False,
        updated_at_ms=store.get_outfit_state("Mio").updated_at_ms,  # type: ignore[union-attr]
    )
    active_loc_after_reroll = [
        r for r in shared_db.list_by_scope(MemoryScopeFilter(owner_ids=("Mio",)))
        if r.slot_key == "Mio:location"
    ]
    assert len(active_loc_after_reroll) == 1
    assert "商店街" in active_loc_after_reroll[0].detail_text

    # 5. Revert to the first completed turn (seq 2).
    replayed_stage: list[str] = []
    fake_window = SimpleNamespace(
        setDisplayWords=lambda html: replayed_stage.append(html),
        setOptions=lambda opts: None,
    )
    report = revert_chat_history(
        1,
        llm_restarted,
        reloaded_ui,
        fake_window,
        history_path=str(session_dir),
    )
    assert report is not None
    assert report.kept_up_to_seq == 2

    # Cascade Check (1): Turns & UI truncated to Turn 1 ("我们在车站集合吧" + reply)
    assert len(store.list_turns()) == 2
    assert len(reloaded_ui) == 2
    assert len(replayed_stage) == 1 and "检票口" in replayed_stage[0]

    # A checkpoint covering only retained turns is still valid. Its exact
    # anchor depends on the tokenizer; no future checkpoint may survive.
    assert all(cp.up_to_seq <= 2 for cp in store.list_compact_checkpoints())
    post_revert_msgs = llm_restarted.get_messages()
    assert post_revert_msgs == store.build_active_llm_messages()
    assert "车站集合" in store.list_turns()[0].raw_message["content"]
    assert "摩天轮" not in json.dumps(post_revert_msgs, ensure_ascii=False)
    assert "水族馆" not in json.dumps(post_revert_msgs, ensure_ascii=False)

    # Cascade Check (3): Memories from seq > 2 (including BEFORE_COMPACT extractions > 2) deleted;
    # superseded "车站" slot restored; pinned memory preserved!
    surviving = shared_db.list_by_scope(MemoryScopeFilter(owner_ids=("Mio",)))
    surviving_texts = [r.detail_text for r in surviving]
    assert any("车站" in t for t in surviving_texts)
    assert any("草莓可丽饼" in t for t in surviving_texts)  # pinned=True survived!
    assert not any("水族馆" in t or "海景餐厅" in t or "商店街" in t or "摩天轮" in t for t in surviving_texts)
    for rec in surviving:
        if not rec.pinned:
            assert rec.source_turn_seq is not None and rec.source_turn_seq <= 2

    # Cascade Check (4): Mio's outfit reverted back to "uniform"!
    reverted_outfit = store.get_outfit_state("Mio")
    assert reverted_outfit is not None
    assert reverted_outfit.active_group == "uniform"


def test_bridge_memory_remember_and_rollback_routes(
    isolated_hybrid_memory_runtime: tuple[HybridMemoryEngine, SqliteHybridStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import frontend_bridge_core.memory as bridge_memory

    monkeypatch.setattr(bridge_memory, "_check_mem0_before_call", lambda: None)
    _engine, shared_db = isolated_hybrid_memory_runtime
    routes_by_path = {route.pattern: route.handler for route in MEMORY_ROUTES}

    remember_handler = routes_by_path["/api/memory/remember"]
    rollback_handler = routes_by_path["/api/memory/rollback"]

    r1 = remember_handler(
        ApiRequest(
            state=None,
            method="POST",
            path="/api/memory/remember",
            query={},
            params={},
            body={
                "characterName": "Mio",
                "content": "Mio当前心情：平静",
                "slotKey": "Mio:mood",
                "memoryMode": "shared",
                "sourceSessionId": "bridge-sess-1",
                "sourceTurnSeq": 2,
            },
        )
    )
    assert r1.status == 200 and r1.data["ok"] is True

    r2 = remember_handler(
        ApiRequest(
            state=None,
            method="POST",
            path="/api/memory/remember",
            query={},
            params={},
            body={
                "characterName": "Mio",
                "content": "Mio当前心情：害羞",
                "slotKey": "Mio:mood",
                "memoryMode": "shared",
                "sourceSessionId": "bridge-sess-1",
                "sourceTurnSeq": 6,
            },
        )
    )
    assert r2.status == 200 and r2.data["ok"] is True

    rb = rollback_handler(
        ApiRequest(
            state=None,
            method="POST",
            path="/api/memory/rollback",
            query={},
            params={},
            body={"sessionId": "bridge-sess-1", "turnSeq": 3},
        )
    )
    assert rb.status == 200
    assert rb.data["ok"] is True
    assert rb.data["rolled_back"] == 1

    active = shared_db.list_by_scope(MemoryScopeFilter(owner_ids=("Mio",)))
    assert len(active) == 1
    assert active[0].detail_text == "Mio当前心情：平静"



def test_compaction_anchor_only_covers_messages_sent_to_the_summarizer(monkeypatch):
    from ai.llm.compact_manager import CompactManager

    hooks = PluginHookDispatcher()
    covered = []
    hooks.register_before_compact(lambda context: covered.append(context.up_to_seq))
    checkpoints = []
    compactor = CompactManager(
        object(), max_tokens=260, compact_threshold=0.50, compact_target_ratio=0.45,
        recent_message_limit=2, hook_dispatcher=hooks,
        on_checkpoint=lambda seq, summary: checkpoints.append((seq, summary)),
    )
    monkeypatch.setattr(compactor, "count_tokens", lambda messages: sum(len(m["content"]) for m in messages))
    monkeypatch.setattr(compactor, "count_text_tokens", len)
    prompts = []

    def summarize(prompt):
        prompts.append(prompt)
        return "summary " * 10

    monkeypatch.setattr(compactor, "_call_llm_for_compaction", summarize)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "older message " * 8, "_turn_seq": 1},
        {"role": "assistant", "content": "keep this recent message", "_turn_seq": 2},
        {"role": "user", "content": "keep current message", "_turn_seq": 3},
    ]

    compacted = compactor.compact_messages(messages)

    assert covered == [1]
    assert [seq for seq, _ in checkpoints] == [1]
    assert "keep this recent message" not in prompts[0]
    assert compacted[-2:] == messages[-2:]
    assert compactor.count_tokens(compacted) <= 117
