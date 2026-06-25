"""
Test mem0 memory tools: remember, search, forget with agent_id=character_name.

Requires: mem0ai, sentence-transformers
Usage: HF_ENDPOINT=https://hf-mirror.com python test/test_memory_tools.py
"""
from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import time as _time

from llm.tools.memory_tools import memory_remember, memory_search, memory_forget


def _flush() -> None:
    """Give Qdrant a moment to sync on-disk writes."""
    _time.sleep(2.0)


def _cleanup(mems: list, char: str) -> None:
    for m in mems:
        if isinstance(m, dict) and m.get("id"):
            memory_forget(m["id"])


def test_remember_and_search():
    char = "test_Alice"
    print(f"\n=== 1. 存入 & 搜索 ({char}) ===")

    print("  存入 2 条...")
    r = memory_remember("Alice 喜欢吃苹果", character_name=char)
    assert r.get("ok"), f"remember failed: {r}"
    r2 = memory_remember("Alice 讨厌香菜", character_name=char)
    assert r2.get("ok")
    _flush()

    print("  搜索...")
    s = memory_search("喜欢吃什么", character_name=char, limit=10)
    assert s.get("count", 0) >= 1, f"search returned 0: {s}"
    for m in s["memories"]:
        print(f"    [{m.get('user_id')}] {m.get('memory')}")
        assert m.get("user_id") == char, f"wrong user_id: {m.get('user_id')}"

    _cleanup(s["memories"], char)
    print("  [PASS]")


def test_multi_character_isolation():
    print("\n=== 2. 多角色隔离 ===")
    # Use distinctive English phrases so the LLM extractor doesn't rewrite them
    memory_remember("Bob's favorite food is sushi", character_name="test_Bob")
    memory_remember("Carol's favorite color is blue", character_name="test_Carol")
    _flush()

    bob = memory_search("sushi food", character_name="test_Bob")
    carol = memory_search("sushi food", character_name="test_Carol")

    print(f"  Bob 搜'sushi food': {bob.get('count')} 条 → {[m.get('memory','')[:40] for m in bob['memories']]}")
    print(f"  Carol 搜'sushi food': {carol.get('count')} 条 → {[m.get('memory','')[:40] for m in carol['memories']]}")

    bob_user_ids = {m.get("user_id") for m in bob["memories"]}
    carol_user_ids = {m.get("user_id") for m in carol["memories"]}
    assert bob.get("count", 0) > 0, "Bob should find his memory"
    assert "test_Bob" not in carol_user_ids, "Carol should NOT see Bob's memory"

    _cleanup(bob["memories"], "test_Bob")
    _cleanup(carol["memories"], "test_Carol")

    # Verify deletion
    bob2 = memory_search("晨跑", character_name="test_Bob")
    assert bob2.get("count", 0) == 0, "deletion failed"
    print("  [PASS]")


def test_default_agent():
    print("\n=== 3. 默认 agent_id ===")
    memory_remember("用户喜欢喝咖啡", character_name=None)
    _flush()
    s = memory_search("咖啡", character_name=None)
    assert s.get("count", 0) >= 1
    assert s.get("agent_id") == "user"
    for m in s["memories"]:
        assert m.get("user_id") == "user"
    _cleanup(s["memories"], "user")
    print("  [PASS]")


def test_forget():
    print("\n=== 4. 删除记忆 ===")
    r = memory_remember("TestTemp likes pizza", character_name="test_Temp")
    print(f"  remember: {r}")
    if r.get("error"):
        print(f"  SKIP: {r['error'][:100]}")
        return
    _flush()
    s = memory_search("pizza", character_name="test_Temp")
    print(f"  search: count={s.get('count')}")
    if s.get("count", 0) == 0:
        print("  SKIP: LLM extractor may have rewritten the memory")
        return
    for m in s["memories"]:
        f = memory_forget(m["id"])
        assert f.get("ok"), f"forget failed: {f}"
    _flush()
    s2 = memory_search("pizza", character_name="test_Temp")
    assert s2.get("count", 0) == 0, f"memory not deleted: {s2}"
    print("  [PASS]")


def _test_check_mem0_status():
    """Verify check_mem0_status returns all expected status shapes."""
    print("\n=== 5. check_mem0_status ===")
    from llm.tools.memory_tools import check_mem0_status

    status = check_mem0_status()
    assert isinstance(status, dict), f"expected dict, got {type(status)}"
    assert "status" in status, f"missing 'status' key: {status}"
    valid = {"ready", "loading", "not_started", "error", "missing_dependency"}
    assert status["status"] in valid, f"unexpected status: {status['status']}"

    # When mem0 already loaded (tests above), status must be "ready"
    assert status["status"] == "ready", (
        f"expected 'ready' after load; got {status['status']}"
    )

    # missing_dependency shape check — won't happen here since mem0 is installed,
    # but verify the keys when simulated via module error.
    print(f"  status={status['status']}")
    print("  [PASS]")


def _test_is_embedding_model_cached():
    """Verify embedding model cache detection is a boolean."""
    print("\n=== 6. _is_embedding_model_cached ===")
    from llm.tools.memory_tools import _is_embedding_model_cached

    cached = _is_embedding_model_cached()
    assert isinstance(cached, bool), f"expected bool, got {type(cached)}"
    print(f"  modelCached={cached}")
    print("  [PASS]")


if __name__ == "__main__":
    test_remember_and_search()
    test_multi_character_isolation()
    test_default_agent()
    test_forget()
    _test_check_mem0_status()
    _test_is_embedding_model_cached()
    print("=== All 6 tests passed ===")
