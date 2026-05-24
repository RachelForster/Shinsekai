"""Unit tests for chat_history — pop_last_assistant_turn (reroll logic)."""

from core.sprite.chat_history import pop_last_assistant_turn


def _uh(msg: str) -> str:
    return f"<b>你</b>：{msg}"


def _ah(name: str, msg: str) -> str:
    return f"<b>{name}</b>：{msg}"


def _u(msg: str) -> dict:
    return {"role": "user", "content": msg}


def _a(msg: str) -> dict:
    return {"role": "assistant", "content": msg}


def _t(call_id: str, name: str, result: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": result, "name": name}


class TestPopLastAssistantTurn:
    def test_single_turn_pops_both(self):
        """一轮问答：user + assistant → 全部 pop，返回 user 文本。"""
        hist = [_uh("hello"), _ah("Alice", "hi")]
        msgs = [_u("hello"), _a("hi")]
        last = pop_last_assistant_turn(hist, msgs)
        assert last == _uh("hello")
        assert hist == []
        assert msgs == []

    def test_second_turn_pops_only_last(self):
        """两轮问答 → 只 pop 第二轮，保留第一轮。"""
        hist = [_uh("hi"), _ah("Bob", "hey"), _uh("how are you"), _ah("Bob", "good")]
        msgs = [_u("hi"), _a("hey"), _u("how are you"), _a("good")]
        last = pop_last_assistant_turn(hist, msgs)
        assert last == _uh("how are you")
        assert hist == [_uh("hi"), _ah("Bob", "hey")]
        assert msgs == [_u("hi"), _a("hey")]

    def test_with_tool_calls(self):
        """user → assistant(tool_use) → tool → assistant → 全部 pop。"""
        hist = [_uh("search"), _ah("Bot", "let me check"), _ah("Bot", "found")]
        msgs = [_u("search"), _a("let me check"), _t("c1", "search", "ok"), _a("found")]
        last = pop_last_assistant_turn(hist, msgs)
        assert last == _uh("search")
        assert hist == []
        assert msgs == []

    def test_no_assistant_yet(self):
        """刚发 user 还没收到回复 → pop 掉这条 user。"""
        hist = [_uh("waiting")]
        msgs = [_u("waiting")]
        last = pop_last_assistant_turn(hist, msgs)
        assert last == _uh("waiting")
        assert hist == []
        assert msgs == []

    def test_empty(self):
        last = pop_last_assistant_turn([], [])
        assert last == ""

    def test_no_user_at_all(self):
        """没有用户消息时不 crash。"""
        hist = [_ah("Bot", "hello")]
        msgs = [_a("hello")]
        last = pop_last_assistant_turn(hist, msgs)
        assert last == ""
        assert hist == []
        assert msgs == []
