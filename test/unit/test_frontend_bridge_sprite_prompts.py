from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

fake_openai = types.ModuleType("openai")
fake_openai.OpenAI = object
sys.modules.setdefault("openai", fake_openai)
fake_tiktoken = types.ModuleType("tiktoken")
fake_tiktoken.get_encoding = lambda *_args, **_kwargs: SimpleNamespace(encode=lambda text: list(str(text)))
fake_tiktoken.encoding_for_model = fake_tiktoken.get_encoding
sys.modules.setdefault("tiktoken", fake_tiktoken)

from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.tasks import _create_task
from frontend_bridge_core.tools import _generate_sprite_prompts
from llm.llm_manager import LLMAdapterFactory
from test.mocks import MockLLMAdapter


class RecordingLLMAdapter(MockLLMAdapter):
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        RecordingLLMAdapter.last_instance = self
        super().__init__(
            responses=[
                json.dumps(
                    {
                        "items": [
                            {
                                "label": "微笑, 挥手",
                                "prompt": "masterpiece, Mika, smile, hand wave, character name: Mika",
                            },
                            {
                                "label": "严肃, 站立",
                                "prompt": "best quality, Mika, serious pose, character name: Mika",
                            },
                        ]
                    }
                )
            ],
            **kwargs,
        )


class _ConfigManager:
    def __init__(self):
        self.character = SimpleNamespace(
            character_setting="Quiet student, 温柔但勇敢。",
            name="Mika",
            sprite_prefix="mika",
        )

    def get_character_by_name(self, name):
        return self.character if name == "Mika" else None

    def get_llm_api_config(self):
        return "MockSpriteLLM", "mock-sprite-model", "https://llm.example/v1", "sk-selected"

    def merged_llm_factory_kwargs(self, provider, base_kwargs):
        return {**base_kwargs, "extra_flag": "from-config"}


def test_generate_sprite_prompts_uses_selected_llm(monkeypatch):
    monkeypatch.setitem(LLMAdapterFactory._adapters, "MockSpriteLLM", RecordingLLMAdapter)
    state = BridgeState(_ConfigManager(), None, None, None)
    task = _create_task(state, kind="test", title="test")

    result = _generate_sprite_prompts(
        state,
        task["id"],
        {"characterName": "Mika", "count": 2, "language": "zh_CN"},
    )

    assert result["provider"] == "MockSpriteLLM"
    assert result["model"] == "mock-sprite-model"
    assert result["items"] == [
        {
            "label": "微笑, 挥手",
            "prompt": "masterpiece, Mika, smile, hand wave, character name: Mika",
        },
        {
            "label": "严肃, 站立",
            "prompt": "best quality, Mika, serious pose, character name: Mika",
        },
    ]
    assert result["prompts"] == [item["prompt"] for item in result["items"]]
    assert RecordingLLMAdapter.last_instance.kwargs == {
        "api_key": "sk-selected",
        "base_url": "https://llm.example/v1",
        "extra_flag": "from-config",
        "model": "mock-sprite-model",
    }
    call = RecordingLLMAdapter.last_instance.call_history[0]
    assert call["stream"] is False
    assert call["kwargs"]["response_format"] == {"type": "json_object"}
    assert "Label language: Simplified Chinese" in call["messages"][1]["content"]
