"""Unit tests for chat_history — pop_last_assistant_turn (reroll logic) and
dialog content parsing."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import sys

# PySide6 is unavailable in CI — fake it before importing history_manager
sys.modules.setdefault("PySide6", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtCore", MagicMock())

from llm.history_manager import (
    _repair_json_string,
    parse_assistant_dialog_content,
    HistoryManager,
)
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


class TestParseAssistantDialogContent:
    """Verify that assistant message content is parsed into dialog lists,
    including tolerance for common LLM output malformations."""

    # ── happy path ───────────────────────────────────────────────────────

    def test_plain_json_object(self):
        dialog = parse_assistant_dialog_content(
            '{"dialog": [{"character_name": "Alice", "sprite": "1", '
            '"speech": "hello"}]}'
        )
        assert len(dialog) == 1
        assert dialog[0]["character_name"] == "Alice"

    def test_fenced_json(self):
        dialog = parse_assistant_dialog_content(
            '```json\n{"dialog": [{"character_name": "Bob", "sprite": "2", '
            '"speech": "hi"}]}\n```'
        )
        assert len(dialog) == 1
        assert dialog[0]["character_name"] == "Bob"

    def test_none_returns_empty(self):
        assert parse_assistant_dialog_content(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_assistant_dialog_content("") == []

    def test_non_dict_returns_empty(self):
        assert parse_assistant_dialog_content('["just", "an", "array"]') == []

    def test_no_dialog_key_returns_empty(self):
        assert parse_assistant_dialog_content('{"other": 1}') == []

    # ── repair: control characters inside string values ──────────────────

    def test_raw_newline_inside_speech_is_escaped(self):
        """Literal newline inside a speech string is repaired and parses."""
        content = (
            '{"dialog": [{"character_name": "Alice", "sprite": "1", '
            '"speech": "line 1\nline 2"}]}'
        )
        dialog = parse_assistant_dialog_content(content)
        assert len(dialog) == 1
        assert dialog[0]["character_name"] == "Alice"
        # After repair the newline is preserved as \\u000a, which json.loads
        # decodes back to a literal newline in the parsed string.
        assert "\n" in dialog[0]["speech"]

    def test_raw_tab_inside_speech_is_escaped(self):
        content = (
            '{"dialog": [{"character_name": "A", "sprite": "1", '
            '"speech": "col1\tcol2"}]}'
        )
        dialog = parse_assistant_dialog_content(content)
        assert len(dialog) == 1

    # ── repair: missing closing quote on long speech fields ─────────────

    def test_missing_closing_quote_before_next_item(self):
        """Simulate LLM dropping the final ``\"`` on a speech value."""
        content = (
            '{\n  "dialog": [\n'
            '    {"character_name": "COT", "sprite": "-1", '
            '"speech": "<summary>long text</summary>\n'
            '    },\n'
            '    {"character_name": "Alice", "sprite": "1", '
            '"speech": "hello"}\n'
            '  ]\n}'
        )
        dialog = parse_assistant_dialog_content(content)
        assert len(dialog) == 2
        assert dialog[0]["character_name"] == "COT"
        assert dialog[1]["character_name"] == "Alice"

    def test_speech_missing_quote_and_closing_braces_is_unfixable(self):
        """When the JSON is missing both the closing quote AND structural
        braces the repair cannot recover and returns empty."""
        content = (
            '{"dialog": [{"character_name": "Alice", "sprite": "1", '
            '"speech": "hello'
        )
        # The string is closed by repair but the missing ]}` cannot be
        # inferred safely.
        dialog = parse_assistant_dialog_content(content)
        assert dialog == []

    def test_missing_quote_before_array_close(self):
        """Speech missing closing quote before ``]`` is repaired."""
        content = (
            '```json\n{\n  "dialog": [\n'
            '    {"character_name": "Narrator", "sprite": "-1", '
            '"speech": "the end'
            '\n  ]\n}\n```'
        )
        # The inner object { } is also missing, so this can't fully recover
        dialog = parse_assistant_dialog_content(content)
        assert dialog == []

    # ── repair: structural newline heuristic ────────────────────────────

    def test_newline_before_close_brace_is_structural(self):
        """Newline followed by ``}`` is treated as JSON structure, not string content."""
        content = (
            '{"dialog": [{"character_name": "X", "sprite": "-1", '
            '"speech": "some text"\n    }\n  ]}'
        )
        dialog = parse_assistant_dialog_content(content)
        assert len(dialog) == 1

    def test_newline_before_open_brace_is_structural(self):
        content = (
            '{"dialog": [{"character_name": "X", "sprite": "-1", '
            '"speech": "some text"\n    }, {"character_name": "Y", '
            '"sprite": "2", "speech": "ok"}]}'
        )
        dialog = parse_assistant_dialog_content(content)
        assert len(dialog) == 2

    # ── real-world COT-style content ────────────────────────────────────

    def test_cot_with_tags_and_newlines(self):
        content = (
            '{"dialog": ['
            '{"character_name": "COT", "sprite": "-1", '
            '"speech": "'
            '<summary>water island said something</summary>'
            '<motivation>fangshi: 1.heard her - paused</motivation>'
            '<plot>they continue walking</plot>'
            '"\n    },\n    {"character_name": "Alice", "sprite": "1", '
            '"speech": "ok"}\n  ]\n}'
        )
        dialog = parse_assistant_dialog_content(content)
        assert len(dialog) == 2
        assert dialog[0]["character_name"] == "COT"
        assert "summary" in dialog[0]["speech"]
        assert dialog[1]["character_name"] == "Alice"


class TestRepairJsonString:
    """Unit tests for the JSON string repair helper."""

    def test_idempotent_on_valid_json(self):
        valid = '{"key": "value", "num": 1}'
        assert _repair_json_string(valid) == valid

    def test_closes_unclosed_string_at_end(self):
        repaired = _repair_json_string('{"key": "value')
        assert repaired.endswith('"')

    def test_escapes_control_chars_inside_string(self):
        repaired = _repair_json_string('{"key": "val\x00ue"}')
        assert "\\u0000" in repaired

    def test_closes_before_structural_brace(self):
        repaired = _repair_json_string(
            '{"dialog": [{"speech": "text\n    }\n  ]\n}'
        )
        # The speech string should be closed before the structural }
        assert '"text"\n    }' in repaired

    def test_closes_before_structural_bracket(self):
        repaired = _repair_json_string(
            '{"dialog": [{"speech": "text\n  ]\n}'
        )
        assert '"text"\n  ]' in repaired

    def test_escaped_quote_not_confused(self):
        repaired = _repair_json_string(
            '{"speech": "he said \\"hello\\""}'
        )
        assert repaired.count('"') % 2 == 0  # balanced quotes


# ====================== 新增：HistoryManager 增量保存与恢复测试 ======================

class TestTmpPath:
    """_tmp_path 静态方法"""

    def test_appends_tmp_suffix(self):
        path = HistoryManager._tmp_path("/data/chat/abc.json")
        assert str(path).endswith(".json.tmp")

    def test_handles_windows_paths(self):
        path = HistoryManager._tmp_path("D:\\data\\chat\\abc.json")
        assert str(path).endswith(".json.tmp")


class TestAppendMessageToTmp:
    """append_message_to_tmp 静态方法"""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.history_file = str(Path(self.tmp_dir) / "test.json")

    def test_creates_tmp_file_and_writes_line(self):
        msg = {"role": "user", "content": "hello"}
        HistoryManager.append_message_to_tmp(self.history_file, msg)

        tmp_path = Path(self.history_file + ".tmp")
        assert tmp_path.exists()
        content = tmp_path.read_text(encoding="utf-8")
        assert '"role"' in content
        assert '"user"' in content
        assert content.endswith(",\n")

    def test_appends_multiple_messages(self):
        HistoryManager.append_message_to_tmp(self.history_file, {"role": "user", "content": "a"})
        HistoryManager.append_message_to_tmp(self.history_file, {"role": "assistant", "content": "b"})

        tmp_path = Path(self.history_file + ".tmp")
        lines = tmp_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_creates_parent_dirs(self):
        deep_file = str(Path(self.tmp_dir) / "sub" / "deep" / "test.json")
        HistoryManager.append_message_to_tmp(deep_file, {"role": "user", "content": "x"})
        assert Path(deep_file + ".tmp").exists()

    def test_does_not_raise_on_none_path(self):
        HistoryManager.append_message_to_tmp(None, {"role": "user", "content": "x"})

    def test_does_not_raise_on_empty_path(self):
        HistoryManager.append_message_to_tmp("", {"role": "user", "content": "x"})


class TestLoadChatHistoryRecovery:
    """load_chat_history 崩溃恢复逻辑"""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.history_file = str(Path(self.tmp_dir) / "test.json")

    def _make_history_manager(self):
        return HistoryManager([])

    def test_normal_load_without_tmp(self):
        msgs = [{"role": "user", "content": "hi"}]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(msgs, f)

        hm = self._make_history_manager()
        result = hm.load_chat_history(self.history_file)
        assert len(result) == 1
        assert result[0]["content"] == "hi"

    def test_recovery_from_tmp_only(self):
        tmp_path = Path(self.history_file + ".tmp")
        tmp_path.write_text(
            '{"role": "user", "content": "recovered"},\n',
            encoding="utf-8"
        )

        hm = self._make_history_manager()
        result = hm.load_chat_history(self.history_file)
        assert len(result) == 1
        assert result[0]["content"] == "recovered"
        # 恢复后应该生成正式文件并删除 tmp
        assert Path(self.history_file).exists()
        assert not tmp_path.exists()

    def test_merges_tmp_into_existing_json(self):
        old_msgs = [{"role": "user", "content": "old"}]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(old_msgs, f)

        tmp_path = Path(self.history_file + ".tmp")
        tmp_path.write_text(
            '{"role": "assistant", "content": "new"},\n',
            encoding="utf-8"
        )

        hm = self._make_history_manager()
        result = hm.load_chat_history(self.history_file)
        assert len(result) == 2
        assert result[0]["content"] == "old"
        assert result[1]["content"] == "new"
        assert not tmp_path.exists()

    def test_dedup_when_last_msg_matches_first_tmp_msg(self):
        old_msgs = [{"role": "user", "content": "dup"}]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(old_msgs, f)

        tmp_path = Path(self.history_file + ".tmp")
        tmp_path.write_text(
            '{"role": "user", "content": "dup"},\n'
            '{"role": "assistant", "content": "new"},\n',
            encoding="utf-8"
        )

        hm = self._make_history_manager()
        result = hm.load_chat_history(self.history_file)
        assert len(result) == 2
        assert result[0]["content"] == "dup"
        assert result[1]["content"] == "new"

    def test_returns_empty_when_both_missing(self):
        hm = self._make_history_manager()
        result = hm.load_chat_history(self.history_file)
        assert result == []

    def test_fallback_to_json_when_tmp_corrupt(self):
        old_msgs = [{"role": "user", "content": "fallback"}]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(old_msgs, f)

        tmp_path = Path(self.history_file + ".tmp")
        tmp_path.write_text("not valid json{{{", encoding="utf-8")

        hm = self._make_history_manager()
        result = hm.load_chat_history(self.history_file)
        assert len(result) == 1
        assert result[0]["content"] == "fallback"


class TestSaveChatHistory:
    """save_chat_history 返回 bool，tmp 由 delete_tmp 独立删除"""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.history_file = str(Path(self.tmp_dir) / "test.json")

    def _make_history_manager(self):
        return HistoryManager([])

    def test_returns_true_on_success(self):
        hm = self._make_history_manager()
        result = hm.save_chat_history(self.history_file, [{"role": "user", "content": "x"}])
        assert result is True
        assert Path(self.history_file).exists()

    def test_returns_true_when_no_file_path(self):
        hm = self._make_history_manager()
        result = hm.save_chat_history(None, [{"role": "user", "content": "x"}])
        assert result is True

    def test_tmp_persists_until_delete_tmp_called(self):
        """save_chat_history 不删 tmp，需要独立调用 delete_tmp"""
        tmp_path = Path(self.history_file + ".tmp")
        tmp_path.write_text("dummy", encoding="utf-8")

        hm = self._make_history_manager()
        hm.save_chat_history(self.history_file, [{"role": "user", "content": "x"}])
        # tmp 仍然存在
        assert tmp_path.exists()

        # 独立调用 delete_tmp 后才删除
        HistoryManager.delete_tmp(self.history_file)
        assert not tmp_path.exists()