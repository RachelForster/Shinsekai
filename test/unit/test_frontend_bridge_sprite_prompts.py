from __future__ import annotations

import json
import shutil
import sys
import types
from pathlib import Path
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
from frontend_bridge_core.characters import _register_character_sprites
from frontend_bridge_core.tools import _generate_sprite_image, _generate_sprite_prompts, _resolve_comfyui_workflow_node_ids
from llm.llm_manager import LLMAdapterFactory
from t2i.t2i_adapter import ComfyUIT2IAdapter
from t2i.t2i_manager import T2IAdapterFactory
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
        self.config = SimpleNamespace(
            api_config=SimpleNamespace(
                t2i_api_url="https://t2i.example",
                t2i_default_workflow_path="D:/workflow.json",
                t2i_extra_configs={"mockt2i": {"ignored": True}},
                t2i_output_node_id="9",
                t2i_prompt_node_id="6",
                t2i_provider="mockt2i",
                t2i_work_path="D:/ComfyUI",
            )
        )
        self.saved = False

    def get_character_by_name(self, name):
        return self.character if name == "Mika" else None

    def get_llm_api_config(self):
        return "MockSpriteLLM", "mock-sprite-model", "https://llm.example/v1", "sk-selected"

    def merged_llm_factory_kwargs(self, provider, base_kwargs):
        return {**base_kwargs, "extra_flag": "from-config"}

    def merged_t2i_factory_kwargs(self, provider, base_kwargs):
        return {**base_kwargs, "extra_flag": "from-config"}

    def reload(self):
        return None

    def save_characters_config(self):
        self.saved = True


class RecordingT2IAdapter:
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        RecordingT2IAdapter.last_instance = self

    def generate_image(self, prompt, file_path=None, **kwargs):
        self.calls.append({"file_path": file_path, "kwargs": kwargs, "prompt": prompt})
        return file_path

    def switch_model(self, model_info):
        self.model_info = model_info


def test_generate_sprite_prompts_uses_selected_llm(monkeypatch):
    monkeypatch.setitem(LLMAdapterFactory._adapters, "MockSpriteLLM", RecordingLLMAdapter)
    state = BridgeState(_ConfigManager(), None, None, None)
    task = _create_task(state, kind="test", title="test")

    result = _generate_sprite_prompts(
        state,
        task["id"],
        {
            "characterName": "Mika",
            "count": 2,
            "language": "zh_CN",
            "positivePromptReference": "anime key visual, detailed eyes, soft rim lighting",
        },
    )

    assert result["provider"] == "MockSpriteLLM"
    assert result["model"] == "mock-sprite-model"
    assert result["items"] == [
        {
            "label": "微笑, 挥手",
            "prompt": "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, Mika, smile, hand wave, character name: Mika",
        },
        {
            "label": "严肃, 站立",
            "prompt": "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, Mika, serious pose, character name: Mika",
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
    assert "masterpiece, best quality, highres, official art, solo, 1 person, single character" in call["messages"][0]["content"]
    assert "Required prompt terms: full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character" in call["messages"][1]["content"]
    assert "multiple views, multiple angles, turnaround sheets, reference sheets" in call["messages"][1]["content"]
    assert "Positive prompt reference from user:" in call["messages"][1]["content"]
    assert "anime key visual, detailed eyes, soft rim lighting" in call["messages"][1]["content"]
    assert "Prefer including applicable terms from this reference" in call["messages"][1]["content"]


def test_generate_sprite_image_uses_selected_t2i(monkeypatch):
    monkeypatch.setitem(T2IAdapterFactory._adapters, "mockt2i", RecordingT2IAdapter)
    state = BridgeState(_ConfigManager(), None, None, None)
    task = _create_task(state, kind="test", title="test")
    output_dir = Path(".tmp_pytest_sprite_prompts").resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)

    try:
        result = _generate_sprite_image(
            state,
            task["id"],
            {
                "characterName": "Mika",
                "label": "微笑, 挥手",
                "negativePrompt": "low quality",
                "outputDir": output_dir.as_posix(),
                "prompt": "masterpiece, Mika, hand wave, character name: Mika",
            },
        )
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)

    assert result["file"].startswith(output_dir.as_posix())
    assert result["files"] == [result["file"]]
    assert result["label"] == "微笑, 挥手"
    assert result["prompt"] == "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, Mika, hand wave, character name: Mika"
    assert isinstance(result["seed"], int)
    assert RecordingT2IAdapter.last_instance.kwargs == {"extra_flag": "from-config"}
    assert len(RecordingT2IAdapter.last_instance.calls) == 1
    call = RecordingT2IAdapter.last_instance.calls[0]
    assert call["file_path"] == result["file"]
    assert call["prompt"] == "masterpiece, best quality, highres, official art, solo, 1 person, single character, full body, visual novel sprite, transparent background, clean lineart, soft cel shading, single view, one pose, centered character, Mika, hand wave, character name: Mika"
    assert call["kwargs"] == {
        "negative_prompt": "low quality, multiple views, multiple angles, turnaround, character sheet, reference sheet, expression sheet, pose sheet, model sheet, split view, multiple panels, collage, duplicated character, clone",
        "seed": result["seed"],
    }


def test_comfyui_adapter_applies_seed_to_sampler_nodes():
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 123, "steps": 20}},
        "4": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 456, "steps": 20}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "prompt"}},
    }

    ComfyUIT2IAdapter._apply_sampler_seed(workflow, 987654321)

    assert workflow["3"]["inputs"]["seed"] == 987654321
    assert workflow["4"]["inputs"]["noise_seed"] == 987654321
    assert workflow["4"]["inputs"]["seed"] == 987654321
    assert workflow["5"]["inputs"] == {"text": "prompt"}


def test_register_character_sprites_adds_generated_paths_and_labels():
    config_manager = _ConfigManager()
    config_manager.character.sprites = [{"path": "data/sprite/mika/existing.png"}]
    config_manager.character.emotion_tags = "立绘 1：neutral\n"
    state = BridgeState(config_manager, None, None, None)
    output_dir = Path(".tmp_pytest_sprite_prompts").resolve()
    image_path = output_dir / "ai_smile.png"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    image_path.write_bytes(b"png")

    try:
        _register_character_sprites(
            state,
            {
                "items": [{"label": "smile, hand wave", "path": image_path.as_posix()}],
                "name": "Mika",
            },
        )
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)

    assert config_manager.saved is True
    assert config_manager.character.sprites == [
        {"path": "data/sprite/mika/existing.png"},
        {"path": image_path.as_posix()},
    ]
    assert config_manager.character.emotion_tags == "立绘 1：neutral\n立绘 2：smile, hand wave\n"


def test_resolve_comfyui_workflow_node_ids_auto_detects_api_workflow_nodes():
    output_dir = Path(".tmp_pytest_sprite_prompts").resolve()
    workflow_path = output_dir / "workflow.json"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    workflow_path.write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"negative": ["43", 0], "positive": ["42", 0]}},
                "17": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
                "42": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive prompt"}},
                "43": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative prompt"}},
            }
        ),
        encoding="utf-8",
    )

    try:
        result = _resolve_comfyui_workflow_node_ids(
            {
                "output_node_id": "9",
                "prompt_node_id": "6",
                "workflow_path": workflow_path.as_posix(),
            }
        )
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)

    assert result["prompt_node_id"] == "42"
    assert result["output_node_id"] == "17"


def test_resolve_comfyui_workflow_node_ids_converts_ui_format_workflow():
    output_dir = Path(".tmp_pytest_sprite_prompts").resolve()
    workflow_path = output_dir / "workflow.json"
    cache_dir = Path(".cache") / "comfyui-api-workflows"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    output_dir.mkdir(parents=True)
    workflow_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": 2, "type": "CLIPTextEncode", "widgets_values": ["positive"]},
                    {"id": 3, "type": "CLIPTextEncode", "widgets_values": ["negative"]},
                    {
                        "id": 4,
                        "inputs": [
                            {"link": 1, "name": "positive"},
                            {"link": 2, "name": "negative"},
                        ],
                        "type": "KSampler",
                        "widgets_values": [123, "fixed", 20, 7.5, "euler", "normal", 1.0],
                    },
                    {"id": 5, "inputs": [{"link": 3, "name": "images"}], "type": "SaveImage"},
                ],
                "links": [
                    [1, 2, 0, 4, 0, "CONDITIONING"],
                    [2, 3, 0, 4, 1, "CONDITIONING"],
                    [3, 4, 0, 5, 0, "IMAGE"],
                ],
            }
        ),
        encoding="utf-8",
    )

    try:
        result = _resolve_comfyui_workflow_node_ids(
            {
                "output_node_id": "9",
                "prompt_node_id": "6",
                "workflow_path": workflow_path.as_posix(),
            }
        )
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)

    assert result["prompt_node_id"] == "2"
    assert result["output_node_id"] == "5"
    assert result["workflow_path"].endswith(".api.json")
