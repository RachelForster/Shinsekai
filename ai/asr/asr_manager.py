"""ASR 适配器工厂；插件注册项由宿主 ``apply_asr_providers(ASRAdapterFactory._adapters)`` 合并（与 LLM/TTS 一致）。"""

from __future__ import annotations

from typing import Type

from sdk.adapters.asr import ASRAdapter

from ai.asr.asr_adapter import VoskAdapter
from ai.asr.sherpa_onnx_adapter import SherpaOnnxAdapter


class ASRAdapterFactory:
    """内置 Vosk 与 Sherpa-ONNX；可选 Whisper 等由插件 ``register_asr_adapter`` 写入同一字典。"""

    _adapters: dict[str, Type[ASRAdapter]] = {
        "vosk": VoskAdapter,
        "sherpa_onnx": SherpaOnnxAdapter,
    }
