"""Compatibility facade re-exporting Qwen3TTSLlamaAdapter and discovery helpers."""

from __future__ import annotations

import requests  # noqa: F401 - preserved for monkeypatches targeting ai.tts.qwen3_tts_adapter.requests
import subprocess  # noqa: F401 - preserved for monkeypatches targeting ai.tts.qwen3_tts_adapter.subprocess
import time  # noqa: F401 - preserved for monkeypatches targeting ai.tts.qwen3_tts_adapter.time

from ai.tts.adapters.qwen3_tts import (
    DEFAULT_QWEN3_TTS_URL,
    Qwen3TTSLlamaAdapter,
    _is_local_server_url,
    _normalize_qwen3_tts_lang,
    _pick_gguf,
    _rank_gguf,
    _resolve_server_executable,
    discover_qwen3_tts_files,
)

__all__ = [
    "DEFAULT_QWEN3_TTS_URL",
    "Qwen3TTSLlamaAdapter",
    "_is_local_server_url",
    "_normalize_qwen3_tts_lang",
    "_pick_gguf",
    "_rank_gguf",
    "_resolve_server_executable",
    "discover_qwen3_tts_files",
]
