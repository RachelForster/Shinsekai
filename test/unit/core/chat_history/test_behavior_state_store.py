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
    BehaviorTurnJournalRecord,
    atomic_write_journal,
)
from core.chat_history.behavior_state_store import (
    BehaviorStateStore,
    BehaviorVersionConflictError,
)
from core.chat_history.sqlite_session_store import SqliteSessionStore
from core.chat_history.storage import (
    load_branch_state,
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
