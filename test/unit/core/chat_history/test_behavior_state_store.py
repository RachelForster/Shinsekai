"""Unit tests for BehaviorStateStore, crash recovery, branch ops, and source isolation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai.memory.rule_recall_planner import RuleRecallPlanner
from application.chat.capabilities.perception import PerceptionSessionCapability, PerceptionTurnContextProvider
from application.chat.host.history import _serialize_history_entries_from_messages
from application.perception.hooks import PerceptionAutoHooks
from core.chat_history.behavior_state_models import (
    BEHAVIOR_TURN_JOURNAL_FILENAME,
    BehaviorIdentityMismatchError,
    BehaviorTurnJournalRecord,
    atomic_write_journal,
    ensure_behavior_state_schema,
)
from core.chat_history.behavior_state_store import (
    BehaviorStateStore,
    BehaviorVersionConflictError,
    read_latest_behavior_id_readonly,
)
from core.chat_history.sqlite_session_store import SqliteSessionStore
from core.chat_history.storage import (
    chat_history_storage_files,
    load_branch_state,
    prune_chat_history_storage,
    remove_chat_history_storage,
    save_branch_state,
)
from core.chat_history.models import (
    CHUNK_FEED_SOURCE,
    PERCEPTION_SOURCE,
    is_real_user_turn_message,
    is_synthetic_internal_message,
    is_synthetic_internal_source,
    render_messages_to_ui_history,
)
from sdk.adapters.memory import TurnRecallInput
from sdk.hooks import BeforeChatContext, MessageAddedContext


def _new_store(tmp_path: Path) -> tuple[SqliteSessionStore, BehaviorStateStore, Path]:
    session_dir = tmp_path / "chat_session"
    session_dir.mkdir(parents=True, exist_ok=True)
    db_store = SqliteSessionStore(session_dir / "history.db")
    behavior_store = BehaviorStateStore(db_store, session_dir)
    return db_store, behavior_store, session_dir


def test_atomic_commit_occ_fork_truncate_and_clear(tmp_path: Path) -> None:
    db_store, behavior_store, _ = _new_store(tmp_path)
    try:
        init = behavior_store.initialize_state(
            branch_id="main",
            behavior_id="novel_theater",
            state={"cursor": 0, "phase": "narrating"},
        )
        assert init.state_version == 1
        assert init.turn_seq == 0

        res1 = behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=1,
            next_state={"cursor": 1, "phase": "narrating"},
            messages=(
                {"role": "user", "source": CHUNK_FEED_SOURCE, "content": "[chunk 0]"},
                {
                    "role": "assistant",
                    "content": '{"dialog":[{"character_name":"Alice","sprite":"0","speech":"Welcome"}]}',
                },
            ),
        )
        assert res1.snapshot.state_version == 2
        assert len(res1.appended_turn_seqs) == 2
        assert not (behavior_store.journal_path and behavior_store.journal_path.exists())

        with pytest.raises(BehaviorVersionConflictError):
            behavior_store.commit_behavior_turn(
                branch_id="main",
                behavior_id="novel_theater",
                expected_state_version=1,
                next_state={"cursor": 2},
            )

        res2 = behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=2,
            next_state={"cursor": 2, "phase": "choices"},
            messages=(
                {"role": "user", "content": "Open door"},
                {
                    "role": "assistant",
                    "content": '{"dialog":[{"character_name":"Alice","sprite":"1","speech":"Creak"}]}',
                },
            ),
        )
        assert res2.snapshot.state_version == 3

        forked = behavior_store.fork_branch("main", "branch-1")
        assert forked is not None and forked.state["cursor"] == 2

        db_store.truncate_after(res1.appended_turn_seqs[-1], branch_id="main")
        restored = behavior_store.get_latest_state("main")
        assert restored is not None
        assert restored.state_version == 2
        assert restored.state["cursor"] == 1

        switched = behavior_store.switch_branch("branch-1")
        assert switched is not None and switched.state_version == 3

        remapped = behavior_store.remap_branch_id("branch-1", "branch-renamed")
        assert remapped >= 1
        assert behavior_store.get_latest_state("branch-renamed") is not None

        db_store.clear(branch_id="main")
        after_clear = behavior_store.get_latest_state("main")
        assert after_clear is not None
        assert after_clear.turn_seq == 0
        assert after_clear.state_version == 1
    finally:
        db_store.close()


def test_crash_recovery_handles_finalized_partial_turns_and_noop(
    tmp_path: Path,
) -> None:
    db_store, behavior_store, session_dir = _new_store(tmp_path)
    try:
        behavior_store.initialize_state(
            branch_id="main",
            behavior_id="novel_theater",
            state={"cursor": 0},
        )
        jpath = session_dir / BEHAVIOR_TURN_JOURNAL_FILENAME

        # Case A: turns + snapshot both committed before crash.
        behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=1,
            next_state={"cursor": 1},
            messages=({"role": "user", "source": CHUNK_FEED_SOURCE, "content": "c1"},),
        )
        committed_seq = db_store.list_turns(branch_id="main")[-1].seq
        atomic_write_journal(
            jpath,
            BehaviorTurnJournalRecord(
                journal_id="j1",
                branch_id="main",
                behavior_id="novel_theater",
                base_turn_seq=0,
                base_state_version=1,
                next_state_version=2,
                created_at_ms=100,
            ).to_dict(),
        )
        rep_a = behavior_store.recover_pending()
        assert rep_a.action == "finalized"
        assert rep_a.restored_snapshot is not None
        assert rep_a.restored_snapshot.state_version == 2
        assert not jpath.exists()

        # Case B: orphan turns inserted without advancing snapshot.
        db_store.append_raw_message(
            {"role": "user", "source": CHUNK_FEED_SOURCE, "content": "orphan"},
            branch_id="main",
        )
        assert len(db_store.list_turns(branch_id="main")) == 2
        atomic_write_journal(
            jpath,
            BehaviorTurnJournalRecord(
                journal_id="j2",
                branch_id="main",
                behavior_id="novel_theater",
                base_turn_seq=committed_seq,
                base_state_version=2,
                next_state_version=3,
                created_at_ms=200,
            ).to_dict(),
        )
        rep_b = behavior_store.recover_pending()
        assert rep_b.action == "rolled_back"
        assert len(db_store.list_turns(branch_id="main")) == 1
        assert rep_b.restored_snapshot is not None
        assert rep_b.restored_snapshot.state_version == 2

        # Case C: crash happened before any DB write.
        atomic_write_journal(
            jpath,
            BehaviorTurnJournalRecord(
                journal_id="j3",
                branch_id="main",
                behavior_id="novel_theater",
                base_turn_seq=committed_seq,
                base_state_version=2,
                next_state_version=3,
                created_at_ms=300,
            ).to_dict(),
        )
        rep_c = behavior_store.recover_pending()
        assert rep_c.action == "cleaned_noop"
        assert not jpath.exists()
    finally:
        db_store.close()


def test_save_branch_state_atomic_and_clear_removes_journal_and_preserves_unmanaged(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    doc_binding = session_dir / "document-binding.json"
    doc_binding.write_text(json.dumps({"docId": "b" * 64}), encoding="utf-8")
    journal = session_dir / BEHAVIOR_TURN_JOURNAL_FILENAME
    journal.write_text("{}", encoding="utf-8")

    save_branch_state(
        session_dir,
        {
            "active": "main",
            "counter": 1,
            "branches": {
                "main": {"id": "main", "label": "Main", "messages": [], "history": []}
            },
        },
    )
    loaded = load_branch_state(session_dir)
    assert loaded is not None and loaded["active"] == "main"

    remove_chat_history_storage(session_dir)
    assert not journal.exists()
    assert doc_binding.is_file()


def test_chunk_feed_synthetic_source_is_isolated_everywhere() -> None:
    chunk_msg = {"role": "user", "source": CHUNK_FEED_SOURCE, "content": "[chunk text]"}
    perc_msg = {"role": "user", "source": PERCEPTION_SOURCE, "content": "[screen]"}
    real_msg = {"role": "user", "source": "user", "content": "Hello"}

    assert is_synthetic_internal_source(CHUNK_FEED_SOURCE) is True
    assert is_synthetic_internal_source(PERCEPTION_SOURCE) is True
    assert is_synthetic_internal_source("user") is False
    assert is_synthetic_internal_message(chunk_msg) is True
    assert is_real_user_turn_message(chunk_msg) is False
    assert is_real_user_turn_message(perc_msg) is False
    assert is_real_user_turn_message(real_msg) is True

    assert render_messages_to_ui_history([chunk_msg]) == []
    assert _serialize_history_entries_from_messages([chunk_msg]) == []

    plan = RuleRecallPlanner().plan(
        TurnRecallInput(user_text="[chunk text]", source=CHUNK_FEED_SOURCE)
    )
    assert plan.should_recall is False

    gatekeeper = MagicMock()
    cache = MagicMock()
    cache.has_context.return_value = True
    cache.take_turn_context.return_value = "screen block"
    hooks = PerceptionAutoHooks(
        rp_input_cache=cache,
        gatekeeper=gatekeeper,
        is_enabled=lambda: True,
        proactive_threshold=lambda: 0.5,
    )
    assert hooks.prepare_turn("t1", CHUNK_FEED_SOURCE) is True
    cache.take_turn_context.assert_not_called()

    provider = PerceptionTurnContextProvider(hooks=hooks, coordinator=MagicMock())
    decision = provider.admit_turn(
        type("Req", (), {"history_turn_id": "t1", "source": CHUNK_FEED_SOURCE})()
    )
    assert decision is not None and decision.admitted is True and decision.record_user_message is False

    before_ctx = BeforeChatContext(
        messages=[dict(chunk_msg)], tools=None, generation_kwargs={}, stream=False
    )
    hooks.before_chat(before_ctx)
    assert before_ctx.messages[0]["content"] == "[chunk text]"

    hooks.message_added(
        MessageAddedContext(role="user", message=dict(chunk_msg), messages=[])
    )
    gatekeeper.notify_conversation_activity.assert_not_called()


def test_zero_message_transition_preserves_initial_snapshot_on_rollback_and_clear(
    tmp_path: Path,
) -> None:
    db_store, behavior_store, _ = _new_store(tmp_path)
    try:
        v1 = behavior_store.initialize_state(
            branch_id="main",
            behavior_id="novel_theater",
            state={"cursor": 0, "phase": "init"},
        )
        assert v1.state_version == 1 and v1.turn_seq == 0

        # State-only transition with empty messages_to_commit must not overwrite v1
        v2 = behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=1,
            next_state={"cursor": 1, "phase": "primed"},
            messages=(),
        )
        assert v2.snapshot.state_version == 2
        assert v2.snapshot.turn_seq == 0
        latest = behavior_store.get_latest_state("main")
        assert latest is not None and latest.state_version == 2

        v3 = behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=2,
            next_state={"cursor": 2, "phase": "playing"},
            messages=[
                {"role": "user", "source": "user", "content": "start"},
                {"role": "assistant", "content": '{"dialog":[{"character_name":"A","speech":"hi"}]}'},
            ],
        )
        assert v3.snapshot.state_version == 3 and v3.snapshot.turn_seq > 0

        # Reverting before the first real user turn via SqliteSessionStore must restore v1
        db_store.truncate_after(0, branch_id="main")
        restored = behavior_store.get_latest_state("main")
        assert restored is not None
        assert restored.state_version == 1
        assert restored.state == {"cursor": 0, "phase": "init"}

        # Repeat via BehaviorStateStore.truncate_after(0) and clear_branch(preserve_initial=True)
        behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=1,
            next_state={"cursor": 5, "phase": "jumped"},
            messages=(),
        )
        restored_trunc = behavior_store.truncate_after("main", 0)
        assert restored_trunc is not None and restored_trunc.state_version == 1
        assert restored_trunc.state == {"cursor": 0, "phase": "init"}

        behavior_store.commit_behavior_turn(
            branch_id="main",
            behavior_id="novel_theater",
            expected_state_version=1,
            next_state={"cursor": 9, "phase": "jumped2"},
            messages=(),
        )
        restored_clear = behavior_store.clear_branch("main", preserve_initial=True)
        assert restored_clear is not None and restored_clear.state_version == 1
        assert restored_clear.state == {"cursor": 0, "phase": "init"}
    finally:
        db_store.close()


def test_legacy_snapshot_table_pk_upgrades_cleanly(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE session_state_snapshots (
                branch_id      TEXT NOT NULL,
                turn_seq       INTEGER NOT NULL,
                behavior_id    TEXT NOT NULL,
                state_version  INTEGER NOT NULL,
                state_json     TEXT NOT NULL,
                created_at_ms  INTEGER NOT NULL,
                PRIMARY KEY (branch_id, turn_seq)
            );
            INSERT INTO session_state_snapshots VALUES ('main', 0, 'demo', 1, '{"cursor":0}', 100);
            """
        )
        ensure_behavior_state_schema(conn)
        conn.commit()
        cols = {
            row["name"]: int(row["pk"] or 0)
            for row in conn.execute("PRAGMA table_info(session_state_snapshots)")
        }
        assert cols["state_version"] > 0
        # Can now insert a second state_version at turn_seq=0 without overwriting v1
        conn.execute(
            "INSERT INTO session_state_snapshots VALUES ('main', 0, 'demo', 2, '{\"cursor\":1}', 200)"
        )
        count = conn.execute("SELECT COUNT(*) FROM session_state_snapshots").fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_remove_and_prune_cleans_crashed_atomic_temp_files(tmp_path: Path) -> None:
    session_dir = tmp_path / "crashed_sess"
    session_dir.mkdir()
    branch_tmp = session_dir / ".branches-deadbeef.tmp"
    journal_tmp = session_dir / ".behavior-journal-cafebabe.tmp"
    branch_tmp.write_text("{", encoding="utf-8")
    journal_tmp.write_text("{", encoding="utf-8")

    owned = set(chat_history_storage_files(session_dir))
    assert branch_tmp in owned
    assert journal_tmp in owned

    remove_chat_history_storage(session_dir)
    prune_chat_history_storage(session_dir)
    assert not branch_tmp.exists()
    assert not journal_tmp.exists()
    assert not session_dir.exists()


def test_behavior_state_store_rejects_mismatched_behavior_identity_and_reads_readonly(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "never_created"
    assert read_latest_behavior_id_readonly(missing_dir) == ""
    assert not missing_dir.exists()

    db_store, behavior_store, session_dir = _new_store(tmp_path)
    try:
        v1 = behavior_store.initialize_state(
            branch_id="main",
            behavior_id="werewolf",
            state={"phase": "day"},
        )
        assert v1.behavior_id == "werewolf"

        with pytest.raises(BehaviorIdentityMismatchError) as init_err:
            behavior_store.initialize_state(
                branch_id="main",
                behavior_id="mafia",
                state={"phase": "lobby"},
            )
        assert init_err.value.expected_behavior_id == "mafia"
        assert init_err.value.actual_behavior_id == "werewolf"

        with pytest.raises(BehaviorIdentityMismatchError) as commit_err:
            behavior_store.commit_behavior_turn(
                branch_id="main",
                behavior_id="mafia",
                expected_state_version=1,
                next_state={"phase": "hijacked"},
            )
        assert commit_err.value.actual_behavior_id == "werewolf"
        assert behavior_store.get_latest_state("main").behavior_id == "werewolf"  # type: ignore[union-attr]
        assert read_latest_behavior_id_readonly(session_dir) == "werewolf"
    finally:
        db_store.close()
    assert read_latest_behavior_id_readonly(session_dir) == "werewolf"
