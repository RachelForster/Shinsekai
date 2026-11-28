"""Unit tests for application.model_providers.catalog."""

from __future__ import annotations

from ai.asr.registry import configure_registered_asr_adapters
from ai.llm.registry import configure_registered_llm_adapters
from ai.t2i.registry import configure_registered_t2i_adapters
from ai.tts.registry import configure_registered_tts_adapters
from application.model_providers.catalog import adapter_catalog, normalize_t2i_provider
from sdk.adapters.asr import ASRAdapter
from sdk.adapters.llm import LLMAdapter
from sdk.adapters.t2i import T2IAdapter
from sdk.adapters.tts import TTSAdapter


def test_adapter_catalog_exposes_visual_backends_and_deepseek_schema() -> None:
    options = {item["value"]: item for item in adapter_catalog()["vision"]}

    assert {
        "auto",
        "chatgpt",
        "claude",
        "deepseek",
        "doubao",
        "gemini",
        "moondream",
        "ollama",
        "qwen",
    } <= options.keys()
    assert options["deepseek"]["schema"]["detail"]["choices"] == [
        "auto",
        "low",
        "high",
        "original",
    ]


def test_adapter_catalog_reflects_dynamic_plugin_registries_and_cleans_up() -> None:
    class _PluginLLM(LLMAdapter):
        def chat(self, messages: list, stream: bool = False, **kwargs):
            return None

    class _PluginTTS(TTSAdapter):
        def generate_speech(self, text, file_path=None, **kwargs):
            return None

        def switch_model(self, model_info):
            return None

    class _PluginT2I(T2IAdapter):
        def generate_image(self, prompt: str, file_path=None, **kwargs):
            return None

        def switch_model(self, model_info):
            return None

    class _PluginASR(ASRAdapter):
        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def get_status(self) -> str:
            return "Stopped"

        def pause(self) -> None:
            return None

        def resume(self) -> None:
            return None

    try:
        configure_registered_llm_adapters({"PluginLLM": _PluginLLM})
        configure_registered_tts_adapters({"plugin-tts": _PluginTTS})
        configure_registered_t2i_adapters({"plugin-t2i": _PluginT2I})
        configure_registered_asr_adapters({"plugin_asr": _PluginASR})

        catalog = adapter_catalog()
        assert "PluginLLM" in {item["value"] for item in catalog["llm"]}
        assert "plugin-tts" in {item["value"] for item in catalog["tts"]}
        assert "plugin-t2i" in {item["value"] for item in catalog["t2i"]}
        assert "plugin_asr" in {item["value"] for item in catalog["asr"]}
        assert normalize_t2i_provider("ComfyUI") == "comfyui"
        assert normalize_t2i_provider("PLUGIN-T2I") == "plugin-t2i"
    finally:
        configure_registered_llm_adapters({})
        configure_registered_tts_adapters({})
        configure_registered_t2i_adapters({})
        configure_registered_asr_adapters({})

    cleared = adapter_catalog()
    assert "PluginLLM" not in {item["value"] for item in cleared["llm"]}
    assert "plugin-tts" not in {item["value"] for item in cleared["tts"]}
    assert "plugin-t2i" not in {item["value"] for item in cleared["t2i"]}
    assert "plugin_asr" not in {item["value"] for item in cleared["asr"]}
