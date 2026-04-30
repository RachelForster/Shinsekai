"""各子系统抽象适配器基类（具体实现位于 ``llm`` / ``tts`` / ``asr`` / ``t2i`` 包）。"""

from sdk.adapters.asr import ASRAdapter, TranscriptionCallback
from sdk.adapters.llm import LLMAdapter
from sdk.adapters.t2i import T2IAdapter
from sdk.adapters.tts import TTSAdapter

__all__ = [
    "ASRAdapter",
    "LLMAdapter",
    "T2IAdapter",
    "TTSAdapter",
    "TranscriptionCallback",
]
