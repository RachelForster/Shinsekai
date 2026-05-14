"""Unit tests for strip_orphaned_tool_calls — clean up orphaned tool_calls and tool results."""

import json
import pytest


def strip_orphaned_tool_calls(msgs: list) -> None:
    """Copy of llm.llm_manager.strip_orphaned_tool_calls for isolated testing."""
    if not msgs:
        return

    # 1. 找出孤立的 tool 消息
    orphan_tool_indices: list[int] = []
    for i, m in enumerate(msgs):
        if m.get("role") != "tool":
            continue
        tc_id = m.get("tool_call_id", "")
        ok = False
        for j in range(i - 1, -1, -1):
            r = msgs[j].get("role", "")
            if r == "user":
                break
            if r == "assistant" and msgs[j].get("tool_calls"):
                if any(tc.get("id") == tc_id for tc in msgs[j]["tool_calls"]):
                    ok = True
                break
        if not ok:
            orphan_tool_indices.append(i)

    # 2. 删孤立的 tool 消息
    for i in reversed(orphan_tool_indices):
        del msgs[i]

    # 3. 重建索引，收集 assistant(tool_calls)
    pending_calls: dict[int, list[dict]] = {}
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            pending_calls[i] = [
                {"id": tc.get("id", ""), "name": tc.get("function", {}).get("name", "")}
                for tc in m["tool_calls"]
            ]

    # 4. 补缺失的 tool 回执
    inserts: list[tuple[int, dict]] = []
    for ai, calls in pending_calls.items():
        seen_ids: set[str] = set()
        insert_at = ai + 1
        for j in range(ai + 1, len(msgs)):
            r = msgs[j].get("role", "")
            if r == "user":
                break
            if r == "tool":
                seen_ids.add(msgs[j].get("tool_call_id", ""))
                insert_at = j + 1
        for tc in calls:
            if tc["id"] not in seen_ids:
                inserts.append((insert_at, {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": json.dumps({"error": "工具调用失败，请尝试其他方式"}),
                }))
                insert_at += 1
    for pos, msg in sorted(inserts, key=lambda x: x[0], reverse=True):
        msgs.insert(pos, msg)


def _a(tc_list: list = None) -> dict:
    """Build an assistant message with tool_calls."""
    m = {"role": "assistant", "content": ""}
    if tc_list:
        m["tool_calls"] = tc_list
    return m


def _atc(*ids: str) -> dict:
    """Build an assistant message with tool_calls having given ids."""
    tcs = [{"id": tid, "type": "function", "function": {"name": f"tool_{tid}", "arguments": "{}"}} for tid in ids]
    return _a(tcs)


def _tool(tc_id: str, content: str = "") -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": content or json.dumps({"result": "ok"})}


def _u(content: str = "hi") -> dict:
    return {"role": "user", "content": content}


PLACEHOLDER = json.dumps({"error": "工具调用失败，请尝试其他方式"})


# ── 场景 1: 健康的一轮 tool call ──────────────────────────────────────────────

def test_healthy_single_tool():
    msgs = [_atc("call_1"), _tool("call_1")]
    before = len(msgs)
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == before
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "tool"


def test_healthy_multi_tool():
    msgs = [_atc("call_1", "call_2"), _tool("call_1"), _tool("call_2")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 3


def test_healthy_tool_then_user():
    msgs = [_atc("call_1"), _tool("call_1"), _u("next")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "tool"
    assert msgs[2]["role"] == "user"


# ── 场景 2: 缺 tool 回执 → 补占位 ──────────────────────────────────────────────

def test_missing_tool_result_fills_placeholder():
    msgs = [_atc("call_1")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 2
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["tool_call_id"] == "call_1"
    assert msgs[1]["content"] == PLACEHOLDER


def test_missing_tool_inserts_after_assistant_not_at_end():
    msgs = [_atc("call_1"), _u("next")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 3
    # user stays at the end
    assert msgs[2]["role"] == "user"
    assert msgs[1]["role"] == "tool"


def test_missing_one_of_two_tools():
    msgs = [_atc("call_1", "call_2"), _tool("call_1")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 3
    assert msgs[1]["tool_call_id"] == "call_1"
    assert msgs[2]["tool_call_id"] == "call_2"
    assert msgs[2]["content"] == PLACEHOLDER


# ── 场景 3: user 插入导致损坏 → 删孤 tool，补占位 ──────────────────────────────

def test_user_between_assistant_and_tool_deletes_orphan_tool():
    """assistant(tc) → user → tool → 删掉孤立的 tool，在 assistant 后补占位"""
    msgs = [_atc("call_1"), _u("interrupt"), _tool("call_1")]
    strip_orphaned_tool_calls(msgs)
    # 孤 tool 被删，占位补在 assistant 后 user 前
    assert len(msgs) == 3
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["content"] == PLACEHOLDER
    assert msgs[2]["role"] == "user"


def test_user_between_assistant_and_tool_multi_user():
    """assistant(tc) → user → user → tool(error) → 删孤 tool，补占位"""
    msgs = [_atc("call_1"), _u("a"), _u("b"), _tool("call_1", json.dumps({"error": ""}))]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 4
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["content"] == PLACEHOLDER
    assert msgs[2]["role"] == "user"
    assert msgs[3]["role"] == "user"


# ── 场景 4: 完全没有 tool_calls ───────────────────────────────────────────────

def test_no_assistant_toolcalls():
    msgs = [_u("hello"), _a(), _u("world")]
    before = list(msgs)
    strip_orphaned_tool_calls(msgs)
    assert msgs == before


def test_empty_messages():
    msgs = []
    strip_orphaned_tool_calls(msgs)
    assert msgs == []


# ── 场景 5: 孤立的 tool 消息（assistant 已丢失） ───────────────────────────────

def test_orphan_tool_without_assistant():
    """tool 消息存在但前面没有 assistant(tc) → 删除"""
    msgs = [_tool("call_orphan", json.dumps({"error": ""})), _u("hello")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_orphan_tool_with_unrelated_assistant():
    """tool 的 id 和前面 assistant 不匹配 → 删除"""
    msgs = [_atc("call_A"), _tool("call_A"), _tool("call_B"), _u("next")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["tool_call_id"] == "call_A"
    assert msgs[2]["role"] == "user"


# ── 场景 6: 多轮对话 ──────────────────────────────────────────────────────────

def test_multiple_healthy_rounds():
    msgs = [
        _atc("c1"), _tool("c1"), _u("ok"),
        _atc("c2"), _tool("c2"), _u("thanks"),
    ]
    before = list(msgs)
    strip_orphaned_tool_calls(msgs)
    assert msgs == before


def test_first_round_broken_second_healthy():
    msgs = [
        _atc("c1"), _u("skip"), _tool("c1"),  # first round broken
        _atc("c2"), _tool("c2"), _u("ok"),     # second round healthy
    ]
    strip_orphaned_tool_calls(msgs)
    # 第一轮孤 tool 删，补占位；第二轮不变
    # expected: [atc(c1), tool(placeholder), u(skip), atc(c2), tool(c2), u(ok)]
    assert len(msgs) == 6
    assert msgs[1]["content"] == PLACEHOLDER
    assert msgs[4]["tool_call_id"] == "c2"


# ── 场景 7: 真实的「用户中断」场景 ──────────────────────────────────────────────

def test_user_interrupted_mid_tool():
    """用户关闭窗口时的典型状态：assistant(tc) 是最后一条消息"""
    msgs = [_u("search bilibili"), _atc("call_search")]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "tool"
    assert msgs[2]["content"] == PLACEHOLDER


def test_user_interrupted_second_round():
    """第一轮正常，第二轮中断"""
    msgs = [
        _u("hi"), _atc("c1"), _tool("c1"),
        _u("search again"), _atc("c2"),
    ]
    strip_orphaned_tool_calls(msgs)
    assert len(msgs) == 6
    # 第二轮 assistant(c2) 后补占位
    assert msgs[4]["role"] == "assistant"
    assert msgs[4]["tool_calls"][0]["id"] == "c2"
    assert msgs[5]["role"] == "tool"
    assert msgs[5]["tool_call_id"] == "c2"
