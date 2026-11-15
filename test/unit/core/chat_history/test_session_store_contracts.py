"""Contract and persistence tests for ConversationSessionPort implementations."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Callable

import pytest

from core.chat_history.in_memory import InMemorySessionStore
from core.chat_history.models import (
    COMPACT_UP_TO_SEQ_KEY,
    MEMORY_MODE_INHERIT_READONLY,
    MEMORY_MODE_ISOLATED,
    MEMORY_MODE_SHARED,
    OutfitState,
    is_compact_summary_message,
    turn_node_from_message,
)
from core.chat_history.ports import (
    clear_session_store_contributions,
    register_session_store_contribution,
)
from core.chat_history.sqlite_session_store import (
    SqliteSessionStore,
    close_all_session_stores,
    open_session_store_for_dir,
    read_full_raw_messages_readonly,
)
from core.chat_history.storage import (
    ACTIVE_HISTORY_FILENAME,
    remove_chat_history_storage,
)
from core.vector_store.in_memory import InMemoryMemoryRepository
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    MemoryRecord,
    MemoryRepository,
    MemoryScopeFilter,
)
from sdk.adapters.session import ConversationSessionPort, SessionStoreContribution


def _assistant_json(character: str, speech: str, sprite: str = "1") -> str:
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


def _make_memory(
    memory_id: str,
    text: str,
    *,
    session_id: str,
    turn_seq: int,
    slot_key: str = "",
    scope: str = SCOPE_CHAR_CROSS_SAVE,
    kind: str = "episodic",
    pinned: bool = False,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        scope=scope,
        owner_id="Mio",
        detail_text=text,
        gist_text=text,
        slot_key=slot_key,
        kind=kind,
        importance=0.8,
        pinned=pinned,
        source_session_id=session_id,
        source_turn_seq=turn_seq,
        embedding=(1.0, 0.0, 0.0, 0.0),
        created_at=float(turn_seq),
        last_recalled_at=float(turn_seq),
    )


@pytest.fixture(params=["in_memory", "sqlite"])
def store_bundle(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> tuple[ConversationSessionPort, MemoryRepository]:
    session_id = "contract-session-001"
    if request.param == "in_memory":
        shared_repo: MemoryRepository = InMemoryMemoryRepository()
        store: ConversationSessionPort = InMemorySessionStore(
            session_id=session_id,
            shared_memory_rollback=shared_repo.rollback_after_turn,
        )
        yield store, shared_repo
        store.close()
    else:
        shared_sqlite = SqliteHybridStore(tmp_path / "shared_memory.db")
        sqlite_store = SqliteSessionStore(
            tmp_path / "session" / "history.db",
            session_id=session_id,
            shared_memory_rollback=shared_sqlite.rollback_after_turn,
        )
        try:
            yield sqlite_store, shared_sqlite
        finally:
            sqlite_store.close()
            shared_sqlite.close()


class TestSessionStoreContractSuite:
    """Liskov contract suite executed identically against InMemory and SQLite stores."""

    def test_satisfies_runtime_protocol_and_default_settings(
        self,
        store_bundle: tuple[ConversationSessionPort, MemoryRepository],
    ) -> None:
        store, _ = store_bundle
        assert isinstance(store, ConversationSessionPort)
        assert store.session_id == "contract-session-001"
        assert store.get_memory_mode() == MEMORY_MODE_SHARED
        assert store.get_auto_outfit_switch() is True

        store.set_memory_mode(MEMORY_MODE_ISOLATED)
        assert store.get_memory_mode() == MEMORY_MODE_ISOLATED
        store.set_memory_mode(MEMORY_MODE_INHERIT_READONLY)
        assert store.get_memory_mode() == MEMORY_MODE_INHERIT_READONLY
        with pytest.raises(ValueError, match="Unsupported memory_mode"):
            store.set_memory_mode("invalid-mode")  # type: ignore[arg-type]
        assert store.get_memory_mode() == MEMORY_MODE_INHERIT_READONLY

        store.set_auto_outfit_switch(False)
        assert store.get_auto_outfit_switch() is False
        store.set_auto_outfit_switch(True)
        assert store.get_auto_outfit_switch() is True

    def test_append_turn_assigns_monotonic_seq_and_strips_transient_keys(
        self,
        store_bundle: tuple[ConversationSessionPort, MemoryRepository],
    ) -> None:
        store, _ = store_bundle
        t1 = store.append_turn(
            turn_node_from_message(
                {
                    "role": "user",
                    "content": "hello",
                    "input_text": "hello",
                    "attachments": [{"kind": "image", "name": "a.png", "path": "/a.png"}],
                    "_turn_seq": 999,
                    COMPACT_UP_TO_SEQ_KEY: 888,
                }
            )
        )
        t2 = store.append_turn(
            turn_node_from_message(
                {"role": "assistant", "content": _assistant_json("Mio", "欢迎回来！")}
            )
        )
        t3 = store.append_turn(
            turn_node_from_message({"role": "user", "content": "去海边吧"})
        )

        assert (t1.seq, t2.seq, t3.seq) == (1, 2, 3)
        assert "_turn_seq" not in t1.raw_message
        assert COMPACT_UP_TO_SEQ_KEY not in t1.raw_message
        assert len(t1.attachments) == 1
        assert t2.speaker == "Mio"
        assert "欢迎回来" in t2.rendered_html

        assert [t.seq for t in store.list_turns()] == [1, 2, 3]
        assert [t.seq for t in store.list_turns(after_seq=1)] == [2, 3]
        assert [t.seq for t in store.list_turns(after_seq=1, up_to_seq=2)] == [2]

    def test_compact_checkpoints_preserve_all_raw_turns_and_assemble_active_window(
        self,
        store_bundle: tuple[ConversationSessionPort, MemoryRepository],
    ) -> None:
        store, _ = store_bundle
        for idx in range(1, 5):
            store.append_turn(
                turn_node_from_message({"role": "user", "content": f"user-{idx}"})
            )
            store.append_turn(
                turn_node_from_message(
                    {"role": "assistant", "content": _assistant_json("Mio", f"reply-{idx}")}
                )
            )

        cp1 = store.add_compact_checkpoint(
            up_to_seq=4,
            rolling_summary="前两轮摘要：讨论了旅行计划。",
        )
        cp2 = store.add_compact_checkpoint(
            up_to_seq=6,
            rolling_summary="前三轮摘要：确定周六出发去海边。",
        )

        assert cp1.up_to_seq == 4
        assert cp2.up_to_seq == 6
        # Non-destructive invariant: all 8 raw turns remain in storage.
        all_turns = store.list_turns()
        assert len(all_turns) == 8

        assert store.get_active_compact_checkpoint() == cp2
        assert store.get_active_compact_checkpoint(max_seq=5) == cp1
        assert store.get_active_compact_checkpoint(max_seq=3) is None

        active_msgs = store.build_active_llm_messages(system_prompt="SYS")
        assert len(active_msgs) == 4  # system + summary(up_to=6) + turn 7 + turn 8
        assert active_msgs[0] == {"role": "system", "content": "SYS"}
        assert is_compact_summary_message(active_msgs[1])
        assert active_msgs[1][COMPACT_UP_TO_SEQ_KEY] == 6
        assert "周六出发去海边" in active_msgs[1]["content"]
        assert active_msgs[2]["content"] == "user-4"
        assert "reply-4" in active_msgs[3]["content"]

    def test_truncate_after_executes_four_in_one_atomic_cascade(
        self,
        store_bundle: tuple[ConversationSessionPort, MemoryRepository],
    ) -> None:
        store, shared_repo = store_bundle
        sid = store.session_id
        scope = MemoryScopeFilter(owner_ids=("Mio",))

        # Turn 1-2: Mio in school_uniform, location = classroom
        store.append_turn(turn_node_from_message({"role": "user", "content": "早安"}))
        store.append_turn(
            turn_node_from_message(
                {"role": "assistant", "content": _assistant_json("Mio", "早安，我们在教室。")}
            )
        )
        store.set_outfit_state(OutfitState("Mio", "school_uniform", updated_at_ms=100))
        for repo in (store.save_memory_repo, shared_repo):
            repo.upsert(
                _make_memory(
                    "mem-loc-1",
                    "Mio当前地点在教室",
                    session_id=sid,
                    turn_seq=2,
                    slot_key="Mio:location",
                )
            )

        # Turn 3-4 + Compact Checkpoint 1 (up_to_seq=4)
        store.append_turn(turn_node_from_message({"role": "user", "content": "中午去哪？"}))
        store.append_turn(
            turn_node_from_message(
                {"role": "assistant", "content": _assistant_json("Mio", "去天台吃便当吧。")}
            )
        )
        store.add_compact_checkpoint(up_to_seq=4, rolling_summary="早上在教室打招呼并约好去天台。")

        # Turn 5-6: Mio switches to casual_dress, location superseded -> rooftop + Checkpoint 2 (up_to_seq=6)
        store.append_turn(turn_node_from_message({"role": "user", "content": "换上便服出发"}))
        store.set_outfit_state(OutfitState("Mio", "casual_dress", updated_at_ms=200))
        for repo in (store.save_memory_repo, shared_repo):
            repo.upsert(
                _make_memory(
                    "mem-loc-2",
                    "Mio当前地点在天台",
                    session_id=sid,
                    turn_seq=5,
                    slot_key="Mio:location",
                )
            )
        store.append_turn(
            turn_node_from_message(
                {"role": "assistant", "content": _assistant_json("Mio", "换好便服来到天台啦。")}
            )
        )
        store.add_compact_checkpoint(up_to_seq=6, rolling_summary="换便服来到天台吃午饭。")

        # Turn 7-8: Mio switches to pajamas, location superseded -> bedroom + pinned & canon memories
        store.append_turn(turn_node_from_message({"role": "user", "content": "晚上回房间休息"}))
        store.set_outfit_state(OutfitState("Mio", "pajamas", locked=True, updated_at_ms=300))
        for repo in (store.save_memory_repo, shared_repo):
            repo.upsert(
                _make_memory(
                    "mem-loc-3",
                    "Mio当前地点在卧室",
                    session_id=sid,
                    turn_seq=7,
                    slot_key="Mio:location",
                )
            )
            repo.upsert(
                _make_memory(
                    "mem-ephemeral-7",
                    "晚饭吃了咖喱饭",
                    session_id=sid,
                    turn_seq=7,
                )
            )
            repo.upsert(
                _make_memory(
                    "mem-pinned-7",
                    "用户手动置顶的重要纪念日",
                    session_id=sid,
                    turn_seq=7,
                    pinned=True,
                )
            )
            repo.upsert(
                _make_memory(
                    "mem-canon-7",
                    "Mio天生怕打雷",
                    session_id=sid,
                    turn_seq=7,
                    scope=SCOPE_CHAR_CANON,
                    kind="canon",
                )
            )
        store.append_turn(
            turn_node_from_message(
                {"role": "assistant", "content": _assistant_json("Mio", "晚安！")}
            )
        )

        # --- Step A: Truncate to seq=5 (between Checkpoint 1 and Checkpoint 2) ---
        report_a = store.truncate_after(5)
        assert report_a.kept_up_to_seq == 5
        assert report_a.deleted_turns == 3
        assert report_a.deleted_checkpoints == 1
        assert report_a.rolled_back_save_memories >= 2
        assert report_a.rolled_back_shared_memories >= 2

        # 1) Turns > 5 gone
        assert [t.seq for t in store.list_turns()] == [1, 2, 3, 4, 5]
        # 2) Checkpoint 2 deleted, Checkpoint 1 (up_to_seq=4) active
        active_cp_a = store.get_active_compact_checkpoint()
        assert active_cp_a is not None and active_cp_a.up_to_seq == 4
        window_a = store.build_active_llm_messages(system_prompt="SYS")
        assert len(window_a) == 3  # SYS + CP1(up_to=4) + Turn 5
        assert "天台吃便当" not in window_a[2]["content"]
        assert window_a[2]["content"] == "换上便服出发"
        # 3) Both save & shared memories rolled back: bedroom & curry gone, rooftop restored, pinned & canon kept
        for repo in (store.save_memory_repo, shared_repo):
            records = {r.id: r for r in repo.list_by_scope(scope)}
            assert "mem-loc-3" not in records
            assert "mem-ephemeral-7" not in records
            assert "mem-loc-2" in records
            assert records["mem-loc-2"].detail_text == "Mio当前地点在天台"
            assert "mem-pinned-7" in records
            assert "mem-canon-7" in records
        # 4) Outfit reverted from pajamas(locked=True) -> casual_dress(locked=False)
        outfit_a = store.get_outfit_state("Mio")
        assert outfit_a is not None
        assert outfit_a.active_group == "casual_dress"
        assert outfit_a.locked is False

        # --- Step B: Truncate further to seq=2 (before Checkpoint 1!) ---
        report_b = store.truncate_after(2)
        assert report_b.deleted_turns == 3
        assert report_b.deleted_checkpoints == 1
        assert store.get_active_compact_checkpoint() is None

        # Active LLM window now contains raw uncompacted turns 1..2 with ZERO summary!
        window_b = store.build_active_llm_messages(system_prompt="SYS")
        assert len(window_b) == 3
        assert not any(is_compact_summary_message(m) for m in window_b)
        assert window_b[1]["content"] == "早安"

        # Superseded slot restored all the way back to classroom (seq=2)
        for repo in (store.save_memory_repo, shared_repo):
            records = {r.id: r for r in repo.list_by_scope(scope)}
            assert "mem-loc-2" not in records
            assert "mem-loc-1" in records
            assert records["mem-loc-1"].detail_text == "Mio当前地点在教室"

        outfit_b = store.get_outfit_state("Mio")
        assert outfit_b is not None and outfit_b.active_group == "school_uniform"

        # --- Step C: Truncate to seq=0 ---
        report_c = store.truncate_after(0)
        assert report_c.kept_up_to_seq == 0
        assert list(store.list_turns()) == []
        assert dict(store.list_outfit_states()) == {}


class TestSqliteSessionStorePersistenceAndMigration:
    """SQLite-specific migration, concurrency, DI contribution, and Windows handle release tests."""

    def teardown_method(self) -> None:
        close_all_session_stores()
        clear_session_store_contributions()

    def test_legacy_migration_retries_after_corrupt_active_json_is_repaired(
        self,
        tmp_path: Path,
    ) -> None:
        session_dir = tmp_path / "legacy-session"
        session_dir.mkdir(parents=True)
        active_path = session_dir / ACTIVE_HISTORY_FILENAME
        active_path.write_text("{corrupt json", encoding="utf-8")

        store = SqliteSessionStore(session_dir / "history.db")
        try:
            merged = store.migrate_from_legacy_files(active_path)
            assert merged is False
            assert store.is_legacy_migrated() is False
            assert "JSONDecodeError" in store.get_migration_error()
            assert list(store.list_turns()) == []

            # Repair active.json and add overlapping .tmp tail; retry must succeed cleanly.
            valid_payload = [
                {"role": "system", "content": "SYS-PROMPT"},
                {"role": "user", "content": "第一句"},
                {"role": "assistant", "content": _assistant_json("Mio", "第一句回复")},
            ]
            active_path.write_text(
                json.dumps(valid_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_journal = Path(str(active_path) + ".tmp")
            tmp_journal.write_text(
                json.dumps(valid_payload[-1], ensure_ascii=False)
                + ",\n"
                + json.dumps({"role": "user", "content": "崩溃前增量句"}, ensure_ascii=False)
                + ",\n",
                encoding="utf-8",
            )

            merged_after_repair = store.migrate_from_legacy_files(active_path)
            assert merged_after_repair is True
            assert store.is_legacy_migrated() is True
            assert store.get_migration_error() == ""
            assert store.get_system_prompt() == "SYS-PROMPT"
            turns = list(store.list_turns())
            assert [t.raw_message["content"] for t in turns] == [
                "第一句",
                _assistant_json("Mio", "第一句回复"),
                "崩溃前增量句",
            ]
        finally:
            store.close()

        readonly = read_full_raw_messages_readonly(session_dir)
        assert readonly is not None
        assert len(readonly) == 4
        assert readonly[0] == {"role": "system", "content": "SYS-PROMPT"}

    def test_concurrent_worker_threads_and_windows_storage_removal(
        self,
        tmp_path: Path,
    ) -> None:
        session_dir = tmp_path / "concurrent-session"
        store = open_session_store_for_dir(session_dir)
        assert isinstance(store, SqliteSessionStore)

        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def worker(worker_id: int) -> None:
            try:
                barrier.wait(timeout=5.0)
                for step in range(5):
                    turn = store.append_raw_message(
                        {"role": "user", "content": f"w{worker_id}-s{step}"}
                    )
                    store.save_memory_repo.upsert(
                        _make_memory(
                            f"m-{worker_id}-{step}",
                            f"memory {worker_id}-{step}",
                            session_id=store.session_id,
                            turn_seq=turn.seq,
                        )
                    )
                    _ = store.list_turns()
            except BaseException as exc:  # pragma: no cover - failure capture
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert errors == []
        assert len(store.list_turns()) == 30

        # Windows file-lock test: remove_chat_history_storage must close SQLite handles
        # and delete history.db + WAL/SHM cleanly without WinError 32.
        remove_chat_history_storage(session_dir)
        assert not (session_dir / "history.db").exists()
        assert not session_dir.exists()

    def test_session_store_contribution_registry_resolves_highest_priority(
        self,
        tmp_path: Path,
    ) -> None:
        custom = InMemorySessionStore(session_id="custom-di-session")
        register_session_store_contribution(
            SessionStoreContribution(
                provider="test-in-memory",
                factory=lambda _path: custom,
                priority=500,
            )
        )
        resolved = open_session_store_for_dir(tmp_path / "di-session")
        assert resolved is custom
