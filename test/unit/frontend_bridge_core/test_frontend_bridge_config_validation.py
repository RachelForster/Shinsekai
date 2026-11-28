from pathlib import Path
from types import SimpleNamespace

import pytest

from config.schema import ApiConfig, AppConfig, SystemConfig
from frontend_bridge_core.config import (
    _app_config_response,
    _save_api_config,
    _state_project_root,
    _validate_api_config_for_save,
)
from application.runtime.state import BridgeState
from core.perception.models import DEFAULT_PERCEPTION_MODEL, GGUF_MODEL_ID, PerceptionConfig


def _valid_config(**overrides):
    data = {
        "llm_provider": "Deepseek",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_base_urls": {"Deepseek": "https://api.deepseek.com/v1"},
        "llm_api_key": {"Deepseek": "sk-test"},
        "llm_model": {"Deepseek": "deepseek-chat"},
        "tts_provider": "gpt-sovits",
        "gpt_sovits_url": "https://example.trycloudflare.com",
        "gpt_sovits_api_path": "",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_gpt_sovits_requires_server_path_even_for_remote_url():
    with pytest.raises(ValueError, match="本地 TTS 引擎需要填写服务启动路径"):
        _validate_api_config_for_save(_valid_config())


def test_local_gpt_sovits_url_requires_server_path():
    with pytest.raises(ValueError, match="本地 TTS 引擎需要填写服务启动路径"):
        _validate_api_config_for_save(_valid_config(gpt_sovits_url="http://127.0.0.1:9880", gpt_sovits_api_path=""))


def test_local_genie_tts_url_requires_server_path():
    with pytest.raises(ValueError, match="本地 TTS 引擎需要填写服务启动路径"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="genie-tts",
                gpt_sovits_url="http://localhost:9880",
                gpt_sovits_api_path="",
            )
        )


def test_local_index_tts_url_requires_server_path():
    with pytest.raises(ValueError, match="本地 TTS 引擎需要填写服务启动路径"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="index-tts",
                gpt_sovits_url="http://localhost:9880",
                gpt_sovits_api_path="",
            )
        )


def test_cosyvoice_does_not_use_shared_server_path():
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="cosyvoice",
            gpt_sovits_url="",
            gpt_sovits_api_path="",
        )
    )


def test_tts_server_path_is_validated_when_provided(tmp_path):
    valid_dir = tmp_path / "gpt-sovits"
    valid_dir.mkdir()

    _validate_api_config_for_save(_valid_config(gpt_sovits_api_path=str(valid_dir)))

    with pytest.raises(ValueError, match="TTS 服务启动路径必须是已存在的目录"):
        _validate_api_config_for_save(_valid_config(gpt_sovits_api_path=str(tmp_path / "missing")))


def test_kaggle_tts_provider_does_not_require_local_server_path(tmp_path):
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="kaggle-gpt-sovits",
            gpt_sovits_api_path=str(tmp_path / "missing"),
        )
    )


def test_deepseek_vision_requires_remote_credentials():
    with pytest.raises(ValueError, match="远程服务还需 API Key"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="cosyvoice",
                llm_provider="ChatGPT",
                llm_base_url="https://api.openai.com/v1",
                llm_base_urls={
                    "ChatGPT": "https://api.openai.com/v1",
                    "Deepseek": "https://api.deepseek.com/v1",
                },
                llm_api_key={"ChatGPT": "sk-chat"},
                llm_model={"ChatGPT": "gpt-4o-mini"},
                vision_provider="deepseek",
                vision_model={"deepseek": "deepseek-flash"},
            )
        )


def test_deepseek_vision_accepts_complete_configuration():
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="cosyvoice",
            vision_provider="deepseek",
            llm_api_key={"Deepseek": "sk-vision"},
            vision_model={"deepseek": "deepseek-flash"},
        )
    )


def test_vision_provider_can_differ_from_active_llm_provider():
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="cosyvoice",
            llm_provider="ChatGPT",
            llm_base_url="https://api.openai.com/v1",
            llm_base_urls={
                "ChatGPT": "https://api.openai.com/v1",
                "Deepseek": "https://deepseek-proxy.example.com/v1",
            },
            llm_api_key={"ChatGPT": "sk-chat", "Deepseek": "sk-deepseek"},
            llm_model={"ChatGPT": "gpt-4o-mini"},
            vision_provider="deepseek",
            vision_model={"deepseek": "deepseek-flash"},
        )
    )


def test_plugin_vision_provider_uses_its_own_adapter_schema():
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="cosyvoice",
            vision_provider="plugin-vision",
        )
    )


def _api_config_with_local_tts() -> ApiConfig:
    return ApiConfig(
        llm_provider="Deepseek",
        llm_base_url="https://api.deepseek.com/v1",
        llm_api_key={"Deepseek": "sk-test"},
        llm_model={"Deepseek": "deepseek-chat"},
        tts_provider="gpt-sovits",
        gpt_sovits_url="http://127.0.0.1:9880",
        gpt_sovits_api_path="",
    )


def _create_gpt_sovits_bundle(root: Path) -> Path:
    bundle_root = root / "data" / "tts_bundles" / "installed" / "gpt_sovits_v2pro"
    bundle_root.mkdir(parents=True)
    (bundle_root / "api_v2.py").write_text("# test bundle\n", encoding="utf-8")
    return bundle_root.resolve()


def _bridge_state_for_config(project_root: Path, app_root: Path):
    config = AppConfig(
        characters=[],
        background_list=[],
        api_config=_api_config_with_local_tts(),
        system_config=SystemConfig(),
    )

    class ConfigManagerStub:
        def __init__(self):
            self.config = config
            self.saved = False

        def save_api_config(self):
            self.saved = True

    manager = ConfigManagerStub()
    state = BridgeState(
        manager,
        None,
        None,
        None,
        app_root_dir=str(app_root),
        project_root_dir=str(project_root),
    )
    return state, manager


def test_tts_bundle_response_uses_project_root_instead_of_app_root(tmp_path, monkeypatch):
    app_root = tmp_path / "Program Files" / "Shinsekai 应用"
    project_root = tmp_path / "D drive" / "User Data 用户数据"
    app_bundle = _create_gpt_sovits_bundle(app_root)
    project_bundle = _create_gpt_sovits_bundle(project_root)
    state, _manager = _bridge_state_for_config(project_root, app_root)
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(tmp_path / "wrong environment root"))
    monkeypatch.setattr("frontend_bridge_core.config._adapter_catalog", lambda: {})

    payload = _app_config_response(state)

    assert payload["api_config"]["gpt_sovits_api_path"] == project_bundle.as_posix()
    assert payload["api_config"]["llm_base_urls"]["Deepseek"] == "https://api.deepseek.com/v1"
    assert payload["tts_bundle_installed_paths"]["gpt-sovits"] == project_bundle.as_posix()
    assert payload["api_config"]["gpt_sovits_api_path"] != app_bundle.as_posix()


def test_save_api_config_defaults_tts_path_under_project_root(tmp_path):
    app_root = tmp_path / "C drive app" / "Shinsekai"
    project_root = tmp_path / "D drive data" / "项目 Root"
    _create_gpt_sovits_bundle(app_root)
    project_bundle = _create_gpt_sovits_bundle(project_root)
    state, manager = _bridge_state_for_config(project_root, app_root)
    payload = _api_config_with_local_tts().model_dump(mode="json")

    saved = _save_api_config(state, payload)

    assert saved.gpt_sovits_api_path == project_bundle.as_posix()
    assert saved.llm_base_urls["Deepseek"] == "https://api.deepseek.com/v1"
    assert manager.config.api_config.gpt_sovits_api_path == project_bundle.as_posix()
    assert manager.saved is True


def test_save_gguf_toggle_switches_managed_server_and_preserves_custom_model(tmp_path, monkeypatch):
    _create_gpt_sovits_bundle(tmp_path)
    state, manager = _bridge_state_for_config(tmp_path, tmp_path)
    api = manager.config.api_config
    api.perception_model = "custom-vision-model"
    api.perception_use_gguf = False
    active = {"managed": True, "baseUrl": api.perception_base_url, "model": api.perception_model}
    switched = []

    def start(**options):
        switched.append(options["model"])
        active["model"] = options["model"]

    monkeypatch.setattr(
        "application.perception.server_launcher.get_perception_server_manager",
        lambda: SimpleNamespace(status=lambda **_: active, start=start),
    )
    payload = api.model_dump(mode="json")
    enabled = _save_api_config(state, {**payload, "perception_use_gguf": True})
    assert enabled.perception_model == "custom-vision-model"
    assert PerceptionConfig.from_api_config(enabled).model == GGUF_MODEL_ID
    disabled = _save_api_config(state, {**payload, "perception_use_gguf": False})
    assert PerceptionConfig.from_api_config(disabled).model == "custom-vision-model"
    assert switched == [GGUF_MODEL_ID, "custom-vision-model"]


def test_previous_gguf_alias_loads_with_the_switch_enabled():
    api = ApiConfig.model_validate({"perception_model": GGUF_MODEL_ID})
    assert api.perception_use_gguf
    assert api.perception_model == DEFAULT_PERCEPTION_MODEL
    assert PerceptionConfig.from_api_config(api).model == GGUF_MODEL_ID


def test_project_root_lookup_supports_legacy_state_and_cwd_fallback(tmp_path, monkeypatch):
    env_root = tmp_path / "legacy env" / "数据 Root"
    easyai_root = tmp_path / "legacy EASYAI env"
    cwd_root = tmp_path / "legacy cwd" / "Project Data"
    app_root = tmp_path / "application root"
    env_root.mkdir(parents=True)
    easyai_root.mkdir(parents=True)
    cwd_root.mkdir(parents=True)
    app_root.mkdir()
    legacy_state = SimpleNamespace(app_root_dir=str(app_root))
    monkeypatch.chdir(cwd_root)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", str(env_root))
    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(easyai_root))

    assert _state_project_root(legacy_state) == env_root.resolve()

    monkeypatch.delenv("SHINSEKAI_PROJECT_ROOT")
    assert _state_project_root(legacy_state) == easyai_root.resolve()

    monkeypatch.delenv("EASYAI_PROJECT_ROOT")
    assert _state_project_root(legacy_state) == cwd_root.resolve()


def _create_bundled_runtime_python(root: Path) -> Path:
    import os

    rel = Path("runtime/python.exe") if os.name == "nt" else Path("runtime/bin/python3")
    exe = root / rel
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake-python")
    return exe.resolve()


def test_app_config_and_save_default_perception_python_to_shinsekai_runtime(tmp_path, monkeypatch):
    app_root = tmp_path / "ShinsekaiApp"
    project_root = tmp_path / "ShinsekaiData"
    _create_gpt_sovits_bundle(project_root)
    bundled_py = _create_bundled_runtime_python(app_root)
    state, manager = _bridge_state_for_config(project_root, app_root)
    monkeypatch.setattr("frontend_bridge_core.config._adapter_catalog", lambda: {})

    payload = _app_config_response(state)
    assert Path(payload["api_config"]["perception_python_path"]).resolve() == bundled_py

    saved_default = _save_api_config(state, _api_config_with_local_tts().model_dump(mode="json"))
    assert Path(saved_default.perception_python_path).resolve() == bundled_py

    custom_py = str(tmp_path / "custom-venv" / "python.exe")
    saved_custom = _save_api_config(
        state,
        {
            **_api_config_with_local_tts().model_dump(mode="json"),
            "perception_python_path": custom_py,
        },
    )
    assert saved_custom.perception_python_path == custom_py
    assert manager.config.api_config.perception_python_path == custom_py


def test_qwen3_tts_gguf_allows_empty_path_validates_non_empty_and_defaults_url(tmp_path):
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="qwen3-tts-gguf",
            gpt_sovits_url="http://127.0.0.1:9882",
            gpt_sovits_api_path="",
        )
    )
    valid_dir = tmp_path / "qwen3-tts"
    valid_dir.mkdir()
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="qwen3-tts-gguf",
            gpt_sovits_url="http://127.0.0.1:9882",
            gpt_sovits_api_path=str(valid_dir),
        )
    )
    with pytest.raises(ValueError, match="TTS 服务启动路径必须是已存在的目录"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="qwen3-tts-gguf",
                gpt_sovits_url="http://127.0.0.1:9882",
                gpt_sovits_api_path=str(tmp_path / "missing"),
            )
        )

    from config.tts_provider_config import QWEN3_TTS_GGUF_DEFAULT_URL, tts_server_url_or_default

    assert tts_server_url_or_default("qwen3-tts-gguf", "") == QWEN3_TTS_GGUF_DEFAULT_URL
    assert tts_server_url_or_default("qwen3-tts-gguf", "http://127.0.0.1:9880") == QWEN3_TTS_GGUF_DEFAULT_URL


def test_api_config_defaults_perception_gguf_and_ocr_enabled():
    import yaml

    api = ApiConfig()
    assert api.perception_use_gguf is True
    assert api.perception_ocr_enabled is True

    runtime_cfg = PerceptionConfig.from_api_config(api)
    assert runtime_cfg.model == GGUF_MODEL_ID
    assert runtime_cfg.ocr_enabled is True
    assert runtime_cfg.use_local_ocr is True

    explicit_off = ApiConfig.model_validate({"perception_use_gguf": False, "perception_ocr_enabled": False})
    assert explicit_off.perception_use_gguf is False
    assert explicit_off.perception_ocr_enabled is False

    portable_api = Path(__file__).resolve().parents[3] / "scripts" / "portable_templates" / "data" / "config" / "api.yaml"
    portable_raw = yaml.safe_load(portable_api.read_text(encoding="utf-8"))
    assert portable_raw["perception_use_gguf"] is True
    assert portable_raw["perception_ocr_enabled"] is True


def test_installed_tts_bundle_paths_verifies_qwen3_tts_gguf_assets(tmp_path, monkeypatch):
    import os
    from config.tts_provider_config import default_tts_work_path, installed_tts_bundle_paths

    monkeypatch.setattr("config.tts_provider_config.shutil.which", lambda _name: None)
    assert "qwen3-tts-gguf" not in installed_tts_bundle_paths(tmp_path)

    qwen_dir = tmp_path / "data" / "models" / "qwen3-tts-gguf"
    qwen_dir.mkdir(parents=True)
    (qwen_dir / "Qwen3-TTS-12Hz-0.6B-Base.Q8_0.gguf").write_bytes(b"weights")
    # Missing mmproj and llama-server -> not ready
    assert "qwen3-tts-gguf" not in installed_tts_bundle_paths(tmp_path)

    (qwen_dir / "Qwen3-TTS-12Hz-0.6B-Base.mmproj-f16.gguf").write_bytes(b"mmproj")
    # Still missing llama-server -> not ready
    assert "qwen3-tts-gguf" not in installed_tts_bundle_paths(tmp_path)

    exe_name = "llama-server.exe" if os.name == "nt" else "llama-server"
    llama_dir = tmp_path / "data" / "models" / "perception-gguf" / "llama.cpp"
    llama_dir.mkdir(parents=True)
    (llama_dir / exe_name).write_bytes(b"llama-bin")

    paths = installed_tts_bundle_paths(tmp_path)
    assert paths["qwen3-tts-gguf"] == qwen_dir.resolve().as_posix()
    assert default_tts_work_path("qwen3-tts-gguf", "", tmp_path) == ""


