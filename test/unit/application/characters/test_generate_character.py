from types import SimpleNamespace

from application.characters import generate_character as generation
from application.characters.generate_character import generate_character
from config.character_manager import CharacterManager
from test.conftest import make_character


class _FakeConfigManager:
    def __init__(self):
        self.model = "model-a"
        self.character = make_character(
            name="Alice",
            character_setting="old",
        )
        self.config = SimpleNamespace(characters=[self.character])
        self.saved = 0

    def get_llm_api_config(self):
        return (
            "Deepseek",
            self.model,
            "https://example.test/v1",
            "sk-test",
        )

    def merged_llm_factory_kwargs(self, _provider, base_kwargs):
        return dict(base_kwargs)

    def get_character_by_name(self, name):
        return self.character if name == self.character.name else None

    def save_characters_config(self):
        self.saved += 1


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


def test_character_generation_accepts_fake_persistence_dependencies():
    character = make_character(name="New", character_setting="seed")

    class ConfigStore:
        current = None

        def get_character_by_name(self, _name):
            return self.current

        def get_llm_api_config(self):
            return "", "", "", ""

        def merged_llm_factory_kwargs(self, _provider, base_kwargs):
            return base_kwargs

        def save_characters_config(self):
            raise AssertionError("incomplete LLM config must not be saved")

    config = ConfigStore()

    class Creator:
        def add_character(self, **_values):
            config.current = character

    result = generate_character(Creator(), config, "New", "seed")

    assert "LLM 配置不完整" in result.message
    assert result.character_setting == "seed"


def test_character_ai_writer_rebuilds_llm_when_model_config_changes(
    monkeypatch,
):
    created_models = []

    def fake_create_adapter(**kwargs):
        created_models.append(kwargs["model"])
        return _FakeAdapter(kwargs["model"])

    monkeypatch.setattr(
        generation.LLMAdapterFactory,
        "create_adapter",
        fake_create_adapter,
    )
    monkeypatch.setattr(
        generation,
        "LLMManager",
        _FakeLLMManager,
    )

    config = _FakeConfigManager()
    manager = CharacterManager()
    manager._config_manager = config

    result = generate_character(manager, config, "Alice", "seed")
    assert result.message == "输出成功"
    assert result.character_setting == "generated:model-a"
    assert result.character_brief == "generated:model-a"
    assert config.character.character_brief == "generated:model-a"

    config.model = "model-b"
    result = generate_character(manager, config, "Alice", "seed")
    assert result.message == "输出成功"
    assert result.character_setting == "generated:model-b"

    result = generate_character(manager, config, "Alice", "seed")
    assert result.message == "输出成功"
    assert result.character_setting == "generated:model-b"

    assert created_models == ["model-a", "model-b"]
    assert config.saved == 6


def test_character_generation_keeps_saved_setting_when_brief_generation_fails(
    monkeypatch,
):
    class BriefFailureLLMManager(_FakeLLMManager):
        def __init__(self, adapter, user_template=""):
            super().__init__(adapter, user_template)
            self.calls = 0

        def chat(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise TimeoutError("brief timed out")
            return "generated setting"

    monkeypatch.setattr(
        generation.LLMAdapterFactory,
        "create_adapter",
        lambda **kwargs: _FakeAdapter(kwargs["model"]),
    )
    monkeypatch.setattr(generation, "LLMManager", BriefFailureLLMManager)

    config = _FakeConfigManager()
    manager = CharacterManager()
    manager._config_manager = config

    result = generate_character(manager, config, "Alice", "seed")

    assert "角色设定输出成功" in result.message
    assert "人物简介生成失败" in result.message
    assert result.character_setting == "generated setting"
    assert config.character.character_setting == "generated setting"
    assert config.saved == 1
