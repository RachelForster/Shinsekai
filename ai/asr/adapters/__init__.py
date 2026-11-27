"""Built-in concrete ASR adapter implementations."""

from ai.asr.adapters.sherpa_onnx import SherpaOnnxAdapter
from ai.asr.adapters.vosk import VOSK_MODEL_PATH, VoskAdapter

__all__ = [
    "SherpaOnnxAdapter",
    "VOSK_MODEL_PATH",
    "VoskAdapter",
]
