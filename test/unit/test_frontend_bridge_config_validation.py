from types import SimpleNamespace

import pytest

from frontend_bridge_core.config import _validate_api_config_for_save


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


def test_kaggle_tts_provider_does_not_require_local_server_path(tmp_path):
    _validate_api_config_for_save(
        _valid_config(
            tts_provider="kaggle-gpt-sovits",
            gpt_sovits_api_path=str(tmp_path / "missing"),
        )
    )
