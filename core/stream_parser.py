"""从 LLM 流式输出中按 JSON 对象切分并解析为 LLMDialogMessage。"""

import json
from typing import Iterator

from .message import LLMDialogMessage


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

    def feed(self, chunk: str) -> Iterator[LLMDialogMessage]:
        """将新到达的文本并入缓冲区，并对其中已完整的 JSON 逐条 yield。"""
        if chunk:
            self._buffer += chunk
            self.accumulated_text += chunk
        yield from self._iter_drain_complete_objects()

    def _iter_drain_complete_objects(self) -> Iterator[LLMDialogMessage]:
        while "}" in self._buffer:
            end_index = self._buffer.find("}") + 1
            start_index = self._buffer.rfind("{", 0, end_index)
            if start_index == -1:
                break
            json_str = self._buffer[start_index:end_index]
            try:
                dialog_item = json.loads(json_str)
                msg = LLMDialogMessage(**dialog_item)
                self._buffer = self._buffer[end_index:].strip()
                yield msg
            except json.JSONDecodeError:
                self._buffer = self._buffer[end_index:].strip()
            except Exception as e:
                print(f"处理失败: {e}")
                self._buffer = self._buffer[end_index:].strip()
                break
