from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.chat import startup


class _AdapterFactory:
    _adapters = {}

    def __init__(self, kind: str, calls: list[tuple[str, dict]]) -> None:
        self.kind = kind
        self.calls = calls

    def create_adapter(self, **kwargs):
        self.calls.append((self.kind, kwargs))
        return f"{self.kind}-adapter"


class _LlmManager:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.messages = []

    def set_messages(self, messages) -> None:
        self.messages = messages


class _TtsManager:
    def __init__(self, *, tts_server_url: str) -> None:
        self.tts_server_url = tts_server_url
        self.adapter = None
        self.language = ""

    def set_tts_adapter(self, *, adapter) -> None:
        self.adapter = adapter

    def set_language(self, language: str) -> None:
        self.language = language


class _T2iManager:
    def __init__(self, adapter) -> None:
        self.adapter = adapter


class _InitChatContext:
    created = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.scale = None
        self.created.append(self)

    def scaled(self, start: float, end: float):
        self.scale = (start, end)
        return self


class _Config:
    def __init__(self, *, llm_provider: str = "openai") -> None:
        self.llm_provider = llm_provider
        self.config = SimpleNamespace(
            api_config=SimpleNamespace(
                max_context_tokens=8192,
                compact_threshold=0.8,
                compact_target_ratio=0.5,
                history_recent_messages=12,
                max_tool_result_chars=1000,
                max_active_tool_groups=3,
                temperature=0.7,
                repetition_penalty=1.1,
                presence_penalty=0.2,
                frequency_penalty=0.1,
                t2i_provider="comfyui-custom",
                t2i_work_path="work",
                t2i_api_url="http://t2i",
                t2i_default_workflow_path="workflow.json",
                t2i_prompt_node_id="1",
                t2i_output_node_id="2",
            ),
            system_config=SimpleNamespace(voice_language="ja"),
        )

    def get_llm_api_config(self):
        return self.llm_provider, "model", "https://llm", "secret"

    def get_gpt_sovits_config(self):
        return "http://tts", "tts-work", "gpt-sovits"

    def merged_llm_factory_kwargs(self, _provider, values):
        return dict(values)

    def merged_tts_factory_kwargs(self, _provider, values):
        return dict(values)

    def merged_t2i_factory_kwargs(self, _provider, values):
        return dict(values)


def _args(**overrides):
    values = {
        "characters": '["Mika"]',
        "headless": False,
        "history": "session.json",
        "init_sprite_path": "",
        "stream_endpoint": "ws://chat",
        "t2i": "comfyui",
        "template": "default",
        "tts": "",
        "workflow": "workflow.yaml",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _runtime(calls, memory_hooks):
    return SimpleNamespace(
        InitChatContext=_InitChatContext,
        LLMAdapterFactory=_AdapterFactory("llm", calls),
        LLMManager=_LlmManager,
        T2IAdapterFactory=_AdapterFactory("t2i", calls),
        T2IManager=_T2iManager,
        TTSAdapterFactory=_AdapterFactory("tts", calls),
        TTSManager=_TtsManager,
        install_memory_hooks=lambda dispatcher, **kwargs: memory_hooks.append(
            (dispatcher, kwargs)
        ),
    )


def test_create_context_assembles_providers_messages_and_hooks(monkeypatch) -> None:
    calls = []
    memory_hooks = []
    runtime = _runtime(calls, memory_hooks)
    dispatcher = SimpleNamespace(dispatch_init_chat=Mock())
    plugin_manager = SimpleNamespace(hook_dispatcher=dispatcher)
    phases = []
    bound = []
    config = _Config()
    messages = [{"role": "user", "content": "hello"}]
    _InitChatContext.created.clear()

    @contextmanager
    def phase(name):
        phases.append(name)
        yield

    monkeypatch.setattr(startup, "_import_provider_runtime", lambda: runtime)
    monkeypatch.setattr(
        startup,
        "_load_plugin_manager",
        lambda received_config, received_runtime: plugin_manager,
    )
    monkeypatch.setattr(
        startup,
        "_load_chat_inputs",
        lambda *_args, **_kwargs: (messages, "system template"),
    )

    context = startup.create_chat_startup_context(
        _args(),
        config=config,
        init_service=SimpleNamespace(report=Mock()),
        translate=lambda key, **_kwargs: key,
        phase=phase,
        output=lambda _message: None,
        on_plugins_loaded=bound.append,
    )

    assert context.config is config
    assert isinstance(context.llm_manager, _LlmManager)
    assert context.messages is messages
    assert context.llm_manager.messages is messages
    assert context.tts_manager.adapter == "tts-adapter"
    assert context.tts_manager.language == "ja"
    assert context.t2i_manager.adapter == "t2i-adapter"
    assert context.plugin_manager is plugin_manager
    assert bound == [plugin_manager]
    assert [kind for kind, _kwargs in calls] == ["t2i", "tts", "llm"]
    assert memory_hooks[0][0] is dispatcher
    assert memory_hooks[0][1]["character_names"] == ["Mika"]
    dispatcher.dispatch_init_chat.assert_called_once_with(_InitChatContext.created[0])
    assert _InitChatContext.created[0].scale == (0.68, 0.82)
    assert phases == [
        "plugins.import",
        "plugins.load",
        "t2i.init",
        "tts.init",
        "template.load",
        "llm.init",
        "chat.init_hooks",
    ]


def test_optional_provider_failures_degrade_to_none() -> None:
    class FailingFactory:
        @staticmethod
        def create_adapter(**_kwargs):
            raise RuntimeError("provider unavailable")

    reports = []
    runtime = SimpleNamespace(
        T2IAdapterFactory=FailingFactory,
        T2IManager=_T2iManager,
        TTSAdapterFactory=FailingFactory,
        TTSManager=_TtsManager,
    )
    service = SimpleNamespace(report=lambda **kwargs: reports.append(kwargs))
    phase = lambda _name: nullcontext()

    t2i = startup._initialize_t2i(_args(), _Config(), service, runtime, phase=phase)
    tts, provider = startup._initialize_tts(
        _args(), _Config(), service, runtime, phase=phase
    )

    assert t2i is None
    assert tts is None
    assert provider == "gpt-sovits"
    assert [report["phase"] for report in reports] == ["t2i.init", "tts.init"]


def test_missing_llm_provider_is_a_fatal_configuration_error(monkeypatch) -> None:
    runtime = _runtime([], [])
    monkeypatch.setattr(startup, "_import_provider_runtime", lambda: runtime)
    monkeypatch.setattr(startup, "_load_plugin_manager", lambda *_args: None)
    monkeypatch.setattr(
        startup,
        "_load_chat_inputs",
        lambda *_args, **_kwargs: ([], "template"),
    )

    with pytest.raises(startup.MissingLlmProviderError):
        startup.create_chat_startup_context(
            _args(t2i="", tts="", history=""),
            config=_Config(llm_provider=""),
            init_service=SimpleNamespace(report=Mock()),
            translate=lambda key, **_kwargs: key,
            output=lambda _message: None,
        )


def test_load_chat_inputs_reads_template_and_history(tmp_path, monkeypatch) -> None:
    template_dir = tmp_path / "data" / "character_templates"
    template_dir.mkdir(parents=True)
    (template_dir / "default.txt").write_text("template body", encoding="utf-8")
    history_path = tmp_path / "history.json"
    history_path.write_text("[]", encoding="utf-8")
    loaded = [{"role": "assistant", "content": "restored"}]
    output = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        startup, "chat_history_active_path", lambda _value: history_path
    )
    monkeypatch.setattr(
        "application.chat.history_state.load_chat_history",
        lambda value: loaded if value == str(history_path) else [],
    )

    messages, template = startup._load_chat_inputs(
        _args(history="history.json"),
        translate=lambda key, **kwargs: f"{key}:{kwargs.get('path', '')}",
        output=output.append,
    )

    assert messages is loaded
    assert template == "template body"
    assert output == ["main.print_load_history:history.json"]


def test_chat_history_presence_requires_a_json_list(tmp_path, monkeypatch) -> None:
    history_path = tmp_path / "history.json"
    monkeypatch.setattr(
        startup, "chat_history_active_path", lambda _value: history_path
    )

    history_path.write_text(json.dumps([]), encoding="utf-8")
    assert startup.chat_history_is_present("history.json") is True

    history_path.write_text(json.dumps({"messages": []}), encoding="utf-8")
    assert startup.chat_history_is_present("history.json") is False

    history_path.write_text("invalid", encoding="utf-8")
    assert startup.chat_history_is_present("history.json") is False
