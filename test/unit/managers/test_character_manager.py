from types import SimpleNamespace

import llm.llm_manager as llm_manager_module
from config.character_manager import CharacterManager
from test.conftest import make_character


class _FakeConfigManager:
    def __init__(self):
        self.model = "model-a"
        self.character = make_character(name="Alice", character_setting="old")
        self.config = SimpleNamespace(characters=[self.character])
        self.saved = 0

    def get_llm_api_config(self):
        return "Deepseek", self.model, "https://example.test/v1", "sk-test"

    def merged_llm_factory_kwargs(self, _provider, base_kwargs):
        return dict(base_kwargs)

    def get_character_by_name(self, name):
        return self.character if name == self.character.name else None

    def save_characters_config(self):
        self.saved += 1
        return True


class _FakeAdapter:
    def __init__(self, model):
        self.model = model


class _FakeLLMManager:
    def __init__(self, adapter, user_template=""):
        self.adapter = adapter
        self.user_template = user_template

    def set_user_template(self, template):
        self.user_template = template

    def chat(self, *_args, **_kwargs):
        return f"generated:{self.adapter.model}"


def test_character_ai_writer_rebuilds_llm_when_model_config_changes(monkeypatch):
    created_models = []

    def fake_create_adapter(**kwargs):
        created_models.append(kwargs["model"])
        return _FakeAdapter(kwargs["model"])

    monkeypatch.setattr(
        llm_manager_module.LLMAdapterFactory,
        "create_adapter",
        fake_create_adapter,
    )
    monkeypatch.setattr(llm_manager_module, "LLMManager", _FakeLLMManager)

    config = _FakeConfigManager()
    manager = CharacterManager()
    manager._config_manager = config

    # 模拟设置页已切换模型，但角色页仍复用同一个 CharacterManager 实例。
    status, setting = manager.generate_character_setting("Alice", "seed")
    assert status == "输出成功"
    assert setting == "generated:model-a"

    config.model = "model-b"
    status, setting = manager.generate_character_setting("Alice", "seed")
    assert status == "输出成功"
    assert setting == "generated:model-b"

    # 第三次配置不变时应该继续复用，防止把缓存修复成每次都重建。
    status, setting = manager.generate_character_setting("Alice", "seed")
    assert status == "输出成功"
    assert setting == "generated:model-b"

    assert created_models == ["model-a", "model-b"]
    assert config.saved == 3
