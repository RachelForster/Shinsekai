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


def _valid_config(**overrides):
    data = {
        "llm_provider": "Deepseek",
        "llm_base_url": "https://api.deepseek.com/v1",
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


def test_tts_server_path_validation_does_not_follow_symlink(tmp_path):
    server = tmp_path / "gpt-sovits"
    alias = tmp_path / "gpt-sovits-alias"
    server.mkdir()
    try:
        alias.symlink_to(server, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        _validate_api_config_for_save(
            _valid_config(gpt_sovits_api_path=alias.as_posix())
        )


def test_relative_tts_server_path_is_resolved_from_selected_project_root(tmp_path, monkeypatch):
    project = tmp_path / "selected-project"
    server = project / "data/tts-server"
    server.mkdir(parents=True)
    unrelated = tmp_path / "unrelated-cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    _validate_api_config_for_save(
        _valid_config(gpt_sovits_api_path="data/tts-server"),
        project_root=project,
    )


def test_kaggle_tts_provider_does_not_require_local_server_path(tmp_path):
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="kaggle-gpt-sovits",
            gpt_sovits_api_path=str(tmp_path / "missing"),
        )
    )


def test_default_empty_t2i_configuration_remains_an_explicit_skip():
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="none",
            t2i_provider="comfyui",
            t2i_api_url="http://127.0.0.1:8188",
            t2i_work_path="",
            t2i_default_workflow_path="",
        )
    )


def test_configured_comfyui_requires_an_existing_workflow(tmp_path):
    with pytest.raises(ValueError, match="默认工作流"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="none",
                t2i_provider="comfyui",
                t2i_api_url="http://localhost:8188",
                t2i_work_path="",
                t2i_default_workflow_path="",
            ),
            project_root=tmp_path,
        )

    with pytest.raises(ValueError, match="已存在的文件"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="none",
                t2i_provider="comfyui",
                t2i_api_url="http://127.0.0.1:8188",
                t2i_work_path="",
                t2i_default_workflow_path="data/workflows/missing.json",
            ),
            project_root=tmp_path,
        )


def test_comfyui_paths_resolve_from_selected_project_root(tmp_path, monkeypatch):
    project = tmp_path / "selected-project"
    workflow = project / "data" / "workflows" / "sprite.json"
    work_directory = project / "data" / "comfyui"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    work_directory.mkdir(parents=True)
    unrelated = tmp_path / "unrelated-cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    _validate_api_config_for_save(
        _valid_config(
            tts_provider="none",
            t2i_provider="comfyui",
            t2i_api_url="http://127.0.0.1:8188",
            t2i_work_path="data/comfyui",
            t2i_default_workflow_path="data/workflows/sprite.json",
        ),
        project_root=project,
    )


def test_comfyui_path_validation_does_not_follow_links(tmp_path):
    project = tmp_path / "project"
    workflow = project / "data" / "workflows" / "sprite.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    linked_work = project / "data" / "comfyui"
    try:
        linked_work.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        _validate_api_config_for_save(
            _valid_config(
                tts_provider="none",
                t2i_provider="comfyui",
                t2i_api_url="http://127.0.0.1:8188",
                t2i_work_path="data/comfyui",
                t2i_default_workflow_path="data/workflows/sprite.json",
            ),
            project_root=project,
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
    assert manager.config.api_config.gpt_sovits_api_path == project_bundle.as_posix()
    assert manager.saved is True


def test_save_api_config_failure_restores_previous_in_memory_config(tmp_path):
    app_root = tmp_path / "app"
    project_root = tmp_path / "project"
    app_root.mkdir()
    _create_gpt_sovits_bundle(project_root)
    state, manager = _bridge_state_for_config(project_root, app_root)
    previous = manager.config.api_config
    payload = _api_config_with_local_tts().model_dump(mode="json")
    payload["llm_model"] = {"Deepseek": "changed-model"}
    manager.save_api_config = lambda: (_ for _ in ()).throw(OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        _save_api_config(state, payload)

    assert manager.config.api_config is previous
    assert manager.config.api_config.llm_model["Deepseek"] == "deepseek-chat"


def test_project_root_lookup_supports_legacy_state_and_stable_app_fallback(tmp_path, monkeypatch):
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
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", str(app_root))
    assert _state_project_root(legacy_state) == app_root.resolve()
