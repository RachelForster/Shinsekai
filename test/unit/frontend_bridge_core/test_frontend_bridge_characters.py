from types import SimpleNamespace

import pytest

from frontend_bridge_core.characters import (
    _save_character,
    _stored_character_path,
    _validate_character_payload,
)


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


def test_local_character_validation_resolves_relative_paths_from_project_not_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    model_dir = project / "data/models/mika"
    model_dir.mkdir(parents=True)
    unrelated.mkdir()
    (model_dir / "model.ckpt").write_bytes(b"gpt")
    (model_dir / "model.pth").write_bytes(b"sovits")
    (model_dir / "ref.wav").write_bytes(b"audio")
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(
        "sdk.ui.validators.audio_duration_between",
        lambda *_args, **_kwargs: (True, ""),
    )

    _validate_character_payload(
        _character_payload(
            gpt_model_path="data/models/mika/model.ckpt",
            sovits_model_path="data/models/mika/model.pth",
            refer_audio_path="data/models/mika/ref.wav",
        ),
        project_root=project,
    )


def test_local_character_validation_rejects_linked_model_directory(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    external = tmp_path / "models"
    (project / "data").mkdir(parents=True)
    external.mkdir()
    (external / "model.ckpt").write_bytes(b"gpt")
    (external / "model.pth").write_bytes(b"sovits")
    (external / "ref.wav").write_bytes(b"audio")
    try:
        (project / "data/models").symlink_to(
            external,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setattr(
        "sdk.ui.validators.audio_duration_between",
        lambda *_args, **_kwargs: (True, ""),
    )

    with pytest.raises(PermissionError, match="symbolic link"):
        _validate_character_payload(
            _character_payload(
                gpt_model_path="data/models/model.ckpt",
                sovits_model_path="data/models/model.pth",
                refer_audio_path="data/models/ref.wav",
            ),
            project_root=project,
        )


def test_save_character_serializes_project_owned_model_paths_as_relative(tmp_path, monkeypatch):
    project = tmp_path / "project"
    model_dir = project / "data/models/mika"
    model_dir.mkdir(parents=True)
    model_paths = {
        "gpt_model_path": model_dir / "model.ckpt",
        "sovits_model_path": model_dir / "model.pth",
        "refer_audio_path": model_dir / "ref.wav",
    }
    for path in model_paths.values():
        path.write_bytes(b"data")

    captured = {}
    character_manager = SimpleNamespace()

    def add_character(*args, **_kwargs):
        captured["paths"] = args[3:6]
        return "人物已添加！", ["Remote Voice"]

    character_manager.add_character = add_character
    config_manager = SimpleNamespace(
        config=SimpleNamespace(
            api_config=SimpleNamespace(tts_provider="gpt-sovits", gpt_sovits_url="https://remote.example")
        ),
        reload=lambda: None,
        get_character_by_name=lambda _name: None,
    )
    state = SimpleNamespace(
        project_root_dir=project.as_posix(),
        character_manager=character_manager,
        config_manager=config_manager,
    )

    result = _save_character(
        state,
        {"character": _character_payload(**{key: path.as_posix() for key, path in model_paths.items()})},
    )

    assert captured["paths"] == (
        "data/models/mika/model.ckpt",
        "data/models/mika/model.pth",
        "data/models/mika/ref.wav",
    )
    assert result["name"] == "Remote Voice"


def test_save_character_preserves_missing_external_model_identity(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "offline-disk/data/models/mika/model.ckpt"

    assert _stored_character_path(external.as_posix(), project) == (
        external.as_posix()
    )


def test_character_save_propagates_rename_to_template_session(monkeypatch):
    renamed: list[tuple[str, str]] = []
    config_manager = SimpleNamespace(
        config=SimpleNamespace(api_config=SimpleNamespace(tts_provider="none")),
        get_character_by_name=lambda name: SimpleNamespace(name=name),
        reload=lambda: None,
    )
    character_manager = SimpleNamespace(
        add_character=lambda *_args, **_kwargs: ("updated", ["B", "C"]),
    )
    state = SimpleNamespace(
        character_manager=character_manager,
        config_manager=config_manager,
    )
    monkeypatch.setattr(
        "frontend_bridge_core.characters._validate_character_payload",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "application.chat.templates._rename_template_session_character",
        lambda _state, old_name, new_name: renamed.append((old_name, new_name)),
    )

    _save_character(
        state,
        {
            "character": {
                "color": "#ffffff",
                "name": "C",
                "sprite_prefix": "a",
            },
            "originalName": "A",
        },
    )

    assert renamed == [("A", "C")]
