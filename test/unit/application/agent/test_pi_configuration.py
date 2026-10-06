from pathlib import Path
from types import SimpleNamespace

import pytest

from application.agent.pi_configuration import prepare_pi_agent, resolve_pi_model
from application.agent.skills import bundled_skill_paths
from core.agent.pi_runtime import PiRuntime
from sdk.agent import AgentRequestError


class ModelConfig:
    def __init__(
        self,
        provider="ChatGPT",
        *,
        key="test-private-key",
        model="test-model",
        url="https://example.com/v1"
    ):
        self.provider, self.key, self.model, self.url = provider, key, model, url
        self.config = SimpleNamespace(
            api_config=SimpleNamespace(max_context_tokens=8192)
        )

    def get_llm_api_config(self):
        return self.provider, self.model, self.url, self.key

    def update_llm_info(self, provider):
        assert provider == self.provider
        return self.url, self.model, self.key


@pytest.mark.parametrize(
    "provider", ["ChatGPT", "Deepseek", "Gemini", "豆包", "通义千问", "Ollama"]
)
def test_existing_compatible_provider_configuration(provider):
    binding = resolve_pi_model(ModelConfig(provider))
    assert binding.model["api"] == "openai-completions"
    assert binding.model["id"] == "test-model"
    assert binding.model["baseUrl"] == "https://example.com/v1"
    assert "test-private-key" not in repr(binding)


def test_claude_uses_existing_url_normalizer():
    binding = resolve_pi_model(
        ModelConfig("Claude", url="https://example.com/v1/messages")
    )
    assert binding.model["baseUrl"] == "https://example.com"
    assert binding.model["api"] == "anthropic-messages"


def test_ollama_reuses_keyless_local_configuration():
    assert resolve_pi_model(ModelConfig("Ollama", key="")).api_key == "ollama"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"key": ""}, "AUTH_REQUIRED"),
        ({"provider": "plugin-native"}, "CAPABILITY_UNSUPPORTED"),
        ({"url": "https://example.com/v1?key=secret"}, "INVALID_REQUEST"),
    ],
)
def test_bad_existing_configuration_is_portable(change, code):
    with pytest.raises(AgentRequestError) as error:
        resolve_pi_model(ModelConfig(**change))
    assert error.value.error.code == code


def test_credentials_rotate_without_entering_backend_dto(tmp_path):
    config = ModelConfig()
    setup = prepare_pi_agent(
        config, root=tmp_path, runtime=PiRuntime(tmp_path / "pi.exe")
    )
    assert "test-private-key" not in setup.backend.model_dump_json()
    assert "test-private-key" not in repr(setup)
    assert setup.worker_environment() == {"SHINSEKAI_PI_API_KEY": "test-private-key"}
    config.key = "rotated-key"
    assert setup.worker_environment()["SHINSEKAI_PI_API_KEY"] == "rotated-key"
    config.model = "changed-model"
    with pytest.raises(AgentRequestError) as error:
        setup.worker_environment()
    assert error.value.error.code == "SESSION_BACKEND_MISMATCH"


def test_runtime_setup_reuses_installer(monkeypatch, tmp_path):
    import application.agent.pi_configuration as module

    calls = []

    class Installer:
        def __init__(self, root):
            calls.append(root)

        def ensure(self, **kwargs):
            return PiRuntime(tmp_path / "pi.exe")

    monkeypatch.setattr(module, "PiRuntimeManager", Installer)
    setup = prepare_pi_agent(ModelConfig(), root=tmp_path)
    assert calls == [tmp_path / "runtimes" / "pi"]
    assert setup.backend.backend_id == "pi"
    assert setup.backend.options["skills"] == bundled_skill_paths()
    assert setup.backend.options["skillLoading"] == "preload"


def test_explicit_empty_skill_mapping_disables_bundled_defaults(tmp_path):
    setup = prepare_pi_agent(
        ModelConfig(),
        root=tmp_path,
        runtime=PiRuntime(tmp_path / "pi.exe"),
        skill_paths={},
    )
    assert setup.backend.options["skills"] == {}
