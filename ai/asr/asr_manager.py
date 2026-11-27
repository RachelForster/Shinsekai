"""Legacy ASR adapter factory facade backed by :mod:`ai.asr.registry`."""

from __future__ import annotations

from ai.asr.asr_adapter import VoskAdapter  # noqa: F401
from ai.asr.registry import get_asr_adapter_registry
from ai.asr.sherpa_onnx_adapter import SherpaOnnxAdapter  # noqa: F401


class ASRAdapterFactory:
    """Compatibility wrapper exposing the live mutable ASR adapter mapping."""

    _adapters = get_asr_adapter_registry().as_mutable_mapping()
