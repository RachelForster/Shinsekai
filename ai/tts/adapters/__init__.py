"""Built-in concrete TTS adapter implementations and shared HTTP helpers."""

from ai.tts.adapters.cosyvoice import CosyVoiceAdapter
from ai.tts.adapters.genie_tts import GenieTTSAdapter
from ai.tts.adapters.gpt_sovits import (
    PRETRAINED_MODEL_CANDIDATES,
    GPTSoVitsAdapter,
    resolve_pretrained_base_models,
)
from ai.tts.adapters.index_tts import IndexTTSAdapter
from ai.tts.adapters.kaggle_gpt_sovits import KaggleGPTSoVitsAdapter, is_kaggle_path
from ai.tts.adapters.local_http import (
    LocalHttpTTSAdapter,
    format_http_error,
    is_local_server_url,
    wait_for_http_service_ready,
)
from ai.tts.qwen3_tts_adapter import Qwen3TTSLlamaAdapter

__all__ = [
    "CosyVoiceAdapter",
    "GPTSoVitsAdapter",
    "GenieTTSAdapter",
    "IndexTTSAdapter",
    "KaggleGPTSoVitsAdapter",
    "LocalHttpTTSAdapter",
    "PRETRAINED_MODEL_CANDIDATES",
    "Qwen3TTSLlamaAdapter",
    "format_http_error",
    "is_kaggle_path",
    "is_local_server_url",
    "resolve_pretrained_base_models",
    "wait_for_http_service_ready",
]
