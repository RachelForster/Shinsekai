"""Compatibility facade re-exporting SherpaOnnxAdapter and model asset constants."""

from __future__ import annotations

from ai.asr.adapters.sherpa_onnx import (
    SENSEVOICE_MODEL,
    SENSEVOICE_TOKENS,
    SHERPA_SENSEVOICE_ASSET,
    SHERPA_SENSEVOICE_REPO,
    SHERPA_ZIPFORMER_ASSET,
    SHERPA_ZIPFORMER_REPO,
    ZIPFORMER_DECODER,
    ZIPFORMER_ENCODER,
    ZIPFORMER_JOINER,
    ZIPFORMER_TOKENS,
    SherpaOnnxAdapter,
    _download_snapshot_via_direct_http,
    _resolve_or_download_asset,
    normalize_sensevoice_language,
)

__all__ = [
    "SENSEVOICE_MODEL",
    "SENSEVOICE_TOKENS",
    "SHERPA_SENSEVOICE_ASSET",
    "SHERPA_SENSEVOICE_REPO",
    "SHERPA_ZIPFORMER_ASSET",
    "SHERPA_ZIPFORMER_REPO",
    "ZIPFORMER_DECODER",
    "ZIPFORMER_ENCODER",
    "ZIPFORMER_JOINER",
    "ZIPFORMER_TOKENS",
    "SherpaOnnxAdapter",
    "_download_snapshot_via_direct_http",
    "_resolve_or_download_asset",
    "normalize_sensevoice_language",
]
