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

    def __init__(self) -> None:
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
                msg = LLMDialogMessage(**dialog_item)
                self._buffer = self._buffer[end_index:].strip()
                yield msg
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
