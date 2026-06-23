import pytest

from frontend_bridge_core.characters import _validate_character_payload


def _character_payload(**overrides):
    data = {
        "name": "Remote Voice",
        "color": "#ffffff",
        "sprite_prefix": "remote_voice",
        "gpt_model_path": "/kaggle/input/voice-model/model.ckpt",
        "sovits_model_path": "/kaggle/input/voice-model/model.pth",
        "refer_audio_path": "/kaggle/input/voice-model/ref.wav",
    }
    data.update(overrides)
    return data


def test_remote_voice_paths_skip_local_file_existence_checks():
    _validate_character_payload(_character_payload(), allow_remote_voice_paths=True)


def test_local_voice_paths_still_require_existing_files():
    with pytest.raises(ValueError, match="GPT 模型路径"):
        _validate_character_payload(_character_payload(), allow_remote_voice_paths=False)


def test_remote_voice_paths_still_validate_model_suffixes():
    with pytest.raises(ValueError, match="SoVITS 模型路径"):
        _validate_character_payload(
            _character_payload(sovits_model_path="/kaggle/input/voice-model/model.ckpt"),
            allow_remote_voice_paths=True,
        )


def test_check_mem0_before_call_returns_none_when_mem0_importable():
    from frontend_bridge_core.characters import _check_mem0_before_call

    result = _check_mem0_before_call()
    # mem0 is importable in the test env → must return None
    assert result is None, f"expected None when mem0 is importable, got {result}"


def test_check_mem0_before_call_returns_dep_error_when_missing(monkeypatch):
    import importlib

    from frontend_bridge_core.characters import _check_mem0_before_call

    def _fake_find_spec(name):
        if name == "mem0":
            return None
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    result = _check_mem0_before_call()
    assert isinstance(result, dict), f"expected dict, got {type(result)}"
    assert result.get("kind") == "missing_dependency"
    assert result.get("moduleName") == "mem0"
    assert result.get("packageName") == "mem0ai[extras]"


def test_get_mem0_status_returns_valid_status():
    from frontend_bridge_core.characters import _get_mem0_status

    result = _get_mem0_status()
    assert isinstance(result, dict)
    assert "status" in result
    valid = {"ready", "loading", "not_started", "error", "missing_dependency"}
    assert result["status"] in valid, f"unexpected status: {result['status']}"


def test_get_mem0_status_missing_dependency_when_not_importable(monkeypatch):
    import importlib

    from frontend_bridge_core.characters import _get_mem0_status

    def _fake_find_spec(name):
        if name == "mem0":
            return None
        return importlib.util.find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    result = _get_mem0_status()
    assert result["status"] == "missing_dependency"
    assert result["moduleName"] == "mem0"
    assert result["packageName"] == "mem0ai[extras]"
