from __future__ import annotations

from pathlib import Path

import pytest

import sdk
from sdk.adapters import ASRAdapter, LLMAdapter, T2IAdapter, TTSAdapter, VisionAdapter
from sdk.handlers import MessageHandler, UIOutputMessageHandler
from sdk.plugin import PluginBase


class _ConcreteASR(ASRAdapter):
    def start(self) -> None:
        return ASRAdapter.start(self)

    def stop(self) -> None:
        return ASRAdapter.stop(self)

    def get_status(self) -> str:
        return ASRAdapter.get_status(self)

    def pause(self) -> None:
        return ASRAdapter.pause(self)

    def resume(self) -> None:
        return ASRAdapter.resume(self)


class _ConcreteLLM(LLMAdapter):
    def chat(self, messages: list, stream: bool = False, **kwargs):
        return LLMAdapter.chat(self, messages, stream=stream, **kwargs)


class _ConcreteT2I(T2IAdapter):
    def generate_image(self, prompt: str, file_path: str | None = None, **kwargs) -> str | None:
        return T2IAdapter.generate_image(self, prompt, file_path=file_path, **kwargs)

    def switch_model(self, model_info):
        return T2IAdapter.switch_model(self, model_info)


class _ConcreteTTS(TTSAdapter):
    def generate_speech(self, text, file_path=None, **kwargs):
        return TTSAdapter.generate_speech(self, text, file_path=file_path, **kwargs)

    def switch_model(self, model_info):
        return TTSAdapter.switch_model(self, model_info)


class _ConcreteVision(VisionAdapter):
    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return f"{prompt}:{len(image_bytes)}"


class _ConcretePlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "com.example.demo_plugin"

    def initialize(self, register, plugin_root: Path, host) -> None:
        return PluginBase.initialize(self, register, plugin_root, host)


class _RootPlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "root"

    def initialize(self, register, plugin_root: Path, host) -> None:
        return None


class _ConcreteMessageHandler(MessageHandler):
    def can_handle(self, msg) -> bool:
        return True


class _ConcreteUIHandler(UIOutputMessageHandler):
    def can_handle(self, out) -> bool:
        return True


def test_adapter_base_defaults_and_abstract_passthroughs():
    seen = []
    asr = _ConcreteASR("zh", lambda text, final: seen.append((text, final)))
    asr.callback("hello", True)

    assert seen == [("hello", True)]
    assert asr.language == "zh"
    assert ASRAdapter.get_config_schema() == {}
    assert asr.start() is None
    assert asr.stop() is None
    assert asr.get_status() is None
    assert asr.pause() is None
    assert asr.resume() is None

    llm = _ConcreteLLM(unused=True)
    llm.set_user_template("template")
    assert llm.user_template == "template"
    assert LLMAdapter.get_config_schema() == {}
    assert LLMAdapter.get_unsupported_chat_params("demo") == set()
    assert llm.chat([], stream=True, temperature=0.1) is None

    assert T2IAdapter.get_config_schema() == {}
    assert _ConcreteT2I().generate_image("prompt", file_path="out.png") is None
    assert _ConcreteT2I().switch_model({"model": "demo"}) is None

    assert TTSAdapter.get_config_schema() == {}
    assert _ConcreteTTS().generate_speech("hello", file_path="out.wav") is None
    assert _ConcreteTTS().switch_model({"voice": "demo"}) is None

    assert _ConcreteVision().describe(b"image", "inspect") == "inspect:5"


def test_plugin_base_defaults_and_names():
    plugin = _ConcretePlugin()

    assert plugin.plugin_version == "0.1.0"
    assert plugin.plugin_name == "demo plugin"
    assert plugin.plugin_description == ""
    assert plugin.plugin_author == ""
    assert plugin.enabled is True
    assert plugin.priority == 100
    assert plugin.initialize(None, Path("."), None) is None
    assert plugin.shutdown() is None
    assert _RootPlugin().plugin_name == "root"


def test_handler_base_noop_lifecycle_methods():
    handler = _ConcreteMessageHandler()
    ui_handler = _ConcreteUIHandler()

    assert handler.can_handle(None) is True
    assert MessageHandler.can_handle(handler, None) is None
    assert handler.pre_process(None) is None
    assert handler.handle(None) is None
    assert handler.post_process(None) is None
    assert handler.init() is None

    assert ui_handler.can_handle(None) is True
    assert UIOutputMessageHandler.can_handle(ui_handler, None) is None
    assert ui_handler.pre_process(None) is None
    assert ui_handler.handle(None) is None
    assert ui_handler.post_process(None) is None
    assert ui_handler.init() is None


def test_sdk_lazy_exports_and_dir():
    assert sdk.LLMAdapter is LLMAdapter
    assert sdk.VisionAdapter is VisionAdapter
    assert "PluginBase" in dir(sdk)

    with pytest.raises(AttributeError, match="does-not-exist"):
        getattr(sdk, "does-not-exist")
