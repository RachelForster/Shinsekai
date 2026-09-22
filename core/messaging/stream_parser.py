"""从 LLM 流式输出中按 JSON 对象切分并解析为 LLMDialogMessage。"""

import json
from typing import Iterator

from sdk.messages import LLMDialogMessage


def _complete_json_object_span(text: str) -> tuple[int, int] | None:
    """Return the first complete top-level JSON object span, if one exists.

    The scanner ignores braces inside JSON strings and supports nested objects.
    If an earlier malformed ``{`` never closes, later candidate starts are still
    considered so the stream can recover from bad prose or broken JSON prefixes.
    """
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start_index in starts:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start_index, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return start_index, index + 1
                if depth < 0:
                    break
    return None


class LlmResponseStreamParser:
    """
    消费文本 chunk，在缓冲区中查找完整的 `{...}` JSON 片段，解析为对话消息。
    与流式/非流式（单 chunk）均可复用；完整原文保存在 accumulated_text 供写入历史。

    feed 为生成器：每成功解析一个对象就 yield 一次，便于立刻写入 tts_queue（与在 worker 里
    边解析边 put 的时序一致；同一 chunk 内多个 JSON 也会在解析第一个后先交付下游）。
    """

    def __init__(self, player_name: str = "", player_speech: str = "") -> None:
        self.player_name = player_name
        self.player_speech = player_speech
        self._buffer = ""
        self.accumulated_text = ""
        self.parse_failures = 0
        self.last_error: str = ""

    @property
    def has_errors(self) -> bool:
        return self.parse_failures > 0

    @property
    def buffer(self) -> str:
        """The current unparsed trailing text (may contain an incomplete JSON)."""
        return self._buffer

    @property
    def unparsed_remainder(self) -> str:
        """流结束后缓冲区里残留的内容（截短便于展示）。"""
        return self._buffer[:200].strip()

    def feed(self, chunk: str) -> Iterator[LLMDialogMessage]:
        """将新到达的文本并入缓冲区，并对其中已完整的 JSON 逐条 yield。"""
        if chunk:
            self._buffer += chunk
            self.accumulated_text += chunk
        yield from self._iter_drain_complete_objects()

    def _iter_drain_complete_objects(self) -> Iterator[LLMDialogMessage]:
        while "}" in self._buffer:
            span = _complete_json_object_span(self._buffer)
            if span is None:
                break
            start_index, end_index = span
            json_str = self._buffer[start_index:end_index]
            try:
                dialog_item = json.loads(json_str)
                messages = self._dialog_messages(dialog_item)
                self._buffer = self._buffer[end_index:].strip()
                yield from messages
            except json.JSONDecodeError:
                self.parse_failures += 1
                _snippet = json_str[:120].replace("\n", " ")
                self.last_error = f"JSON 解析失败 ({_snippet}…)"
                self._buffer = self._buffer[end_index:].strip()
            except Exception as e:
                self.parse_failures += 1
                self.last_error = str(e)[:200]
                self._buffer = self._buffer[end_index:].strip()
                break

    def _dialog_messages(self, dialog_item: object) -> list[LLMDialogMessage]:
        """Turn one parsed JSON object into dialogue messages.

        The output contract wraps utterances in ``{"dialog": [ {...}, ... ]}``.
        While streaming, the inner objects each complete before the wrapper's
        closing brace arrives, so they are drained individually. A non-streaming
        response instead delivers the whole wrapper in a single chunk, so unwrap
        it here into its utterances; both paths then yield the same messages.
        The ``dialog`` key matches ``parse_assistant_dialog_content``.
        """
        player_messages = []
        if self.player_name and isinstance(dialog_item, dict):
            speech = dialog_item.get("player_speech")
            if speech is None and dialog_item and set(dialog_item) <= {"translate"}:
                speech = dialog_item
            if self.player_speech and isinstance(speech, dict):
                translated = str(speech.get("translate") or "").strip()
                if translated:
                    player_message = LLMDialogMessage(
                        name=self.player_name,
                        text=self.player_speech,
                        translate=translated,
                        sprite="-1",
                    )
                    player_message._player_input = True
                    player_messages.append(player_message)
                    if speech is dialog_item:
                        return player_messages
            portrait = dialog_item.get("player_portrait")
            if portrait is None and dialog_item and set(dialog_item) <= {"sprite", "vibe"}:
                portrait = dialog_item
            if isinstance(portrait, dict) and portrait and set(portrait) <= {"sprite", "vibe"}:
                player_messages.append(LLMDialogMessage(
                    name=self.player_name, text="", sprite=portrait.get("sprite", "-1"), vibe=portrait.get("vibe", ""),
                ))
                if portrait is dialog_item or ("dialog" not in dialog_item and "character_name" not in dialog_item):
                    return player_messages
        if isinstance(dialog_item, dict) and isinstance(dialog_item.get("dialog"), list):
            items = [item for item in dialog_item["dialog"] if isinstance(item, dict)]
        else:
            items = [dialog_item]
        return player_messages + [LLMDialogMessage(**item) for item in items]
