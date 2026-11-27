"""Compatibility re-export facade for built-in TTS adapters.

Concrete implementations now live under :mod:`ai.tts.adapters`.
"""

from __future__ import annotations

# Keep stdlib/requests module attributes on this facade so legacy tests using
# monkeypatch.setattr("ai.tts.tts_adapter.requests.Session.get" / "subprocess.Popen" / "time.sleep")
# continue to patch the shared runtime modules cleanly.
import requests  # noqa: F401
import subprocess  # noqa: F401
import time  # noqa: F401

from ai.tts.adapters import (
    PRETRAINED_MODEL_CANDIDATES,
    CosyVoiceAdapter,
    GPTSoVitsAdapter,
    GenieTTSAdapter,
    IndexTTSAdapter,
    KaggleGPTSoVitsAdapter,
    LocalHttpTTSAdapter,
    Qwen3TTSLlamaAdapter,
    is_kaggle_path as _is_kaggle_path,
    is_local_server_url as _is_local_server_url,
    resolve_pretrained_base_models,
    wait_for_http_service_ready as _wait_for_http_service_ready,
)
from sdk.adapters import TTSAdapter

__all__ = [
    "CosyVoiceAdapter",
    "GPTSoVitsAdapter",
    "GenieTTSAdapter",
    "IndexTTSAdapter",
    "KaggleGPTSoVitsAdapter",
    "LocalHttpTTSAdapter",
    "PRETRAINED_MODEL_CANDIDATES",
    "Qwen3TTSLlamaAdapter",
    "TTSAdapter",
    "_is_kaggle_path",
    "_is_local_server_url",
    "_wait_for_http_service_ready",
    "resolve_pretrained_base_models",
]
