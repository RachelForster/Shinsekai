from __future__ import annotations

import os
from pathlib import Path

import config.network_proxy as network_proxy
import pytest
import yaml
from config.config_manager import (
    ConfigManager,
    _migrate_config_asset_paths,
    _normalize_config_payload_paths,
)
from config.schema import AppConfig, ApiConfig, Background, Character, SystemConfig
from config.sprite_voice import normalize_sprite_voice_types


def _config_manager_with_api(**api_overrides) -> ConfigManager:
    manager = object.__new__(ConfigManager)
    api_config = ApiConfig(
        llm_provider=api_overrides.pop("llm_provider", "Deepseek"),
        llm_api_key=api_overrides.pop("llm_api_key", {"Deepseek": "sk-test"}),
        llm_model=api_overrides.pop("llm_model", {"Deepseek": "deepseek-chat"}),
        **api_overrides,
    )
    manager._config = AppConfig(
        api_config=api_config,
        system_config=SystemConfig(),
        characters=[Character(name="Test", color="#ffffff", sprite_prefix="test")],
        background_list=[Background(name="Default", sprite_prefix="default")],
    )
    return manager


def test_config_manager_binds_relative_paths_to_authoritative_project_root(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    project_root.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project_root.as_posix())
    monkeypatch.chdir(unrelated)
    manager = object.__new__(ConfigManager)

    manager._bind_project_paths()

    assert manager._API_CONFIG_PATH == project_root / "data" / "config" / "api.yaml"
    assert manager._EFFECT_CONFIG_PATH == project_root / "data" / "config" / "effect.yaml"


def test_version_metadata_comes_from_application_resources_not_writable_project(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    source = tmp_path / "source"
    project.mkdir()
    source.mkdir()
    (project / "VERSION").write_text("project-spoof", encoding="utf-8")
    (source / "VERSION").write_text("1.2.3", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", source.as_posix())
    manager = object.__new__(ConfigManager)
    manager._bind_project_paths()

    assert manager.version == "1.2.3"


def test_config_manager_refuses_config_paths_through_external_data_symlink(tmp_path, monkeypatch):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (project / "data").symlink_to(external, target_is_directory=True)
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    manager = object.__new__(ConfigManager)

    with pytest.raises(PermissionError, match="escapes project root"):
        manager._bind_project_paths()


def test_config_manager_revalidates_storage_when_symlink_appears_after_binding(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    manager = object.__new__(ConfigManager)
    manager._bind_project_paths()
    (project / "data").symlink_to(external, target_is_directory=True)

    with pytest.raises(PermissionError, match="symbolic links"):
        manager._save_single_config(manager._SYSTEM_CONFIG_PATH, {"language": "zh_CN"})

    assert list(external.iterdir()) == []


def test_config_write_is_atomic_and_preserves_previous_file_on_dump_failure(
    tmp_path,
    monkeypatch,
):
    manager = object.__new__(ConfigManager)
    manager._project_root = tmp_path
    target = tmp_path / "data/config/system_config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("previous: true\n", encoding="utf-8")

    def fail_dump(*_args, **_kwargs):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr("config.config_manager.yaml.dump", fail_dump)

    with pytest.raises(RuntimeError, match="serialization failed"):
        manager._save_single_config(target, {"replacement": True})

    assert target.read_text(encoding="utf-8") == "previous: true\n"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_config_write_publishes_complete_yaml(tmp_path):
    manager = object.__new__(ConfigManager)
    manager._project_root = tmp_path
    target = tmp_path / "data/config/system_config.yaml"

    manager._save_single_config(target, {"language": "日本語", "items": [1, 2]})

    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {
        "language": "日本語",
        "items": [1, 2],
    }


def test_config_write_rejects_lexical_alias_before_creating_file(tmp_path):
    manager = object.__new__(ConfigManager)
    manager._project_root = tmp_path
    alias = f"{tmp_path.as_posix()}/data/./config/system_config.yaml"

    with pytest.raises(ValueError, match="lexical path aliases"):
        manager._save_single_config(alias, {"language": "zh_CN"})

    assert not (tmp_path / "data").exists()


def test_stale_install_asset_paths_migrate_to_portable_project_paths(tmp_path):
    project = tmp_path / "new-project"
    old = tmp_path / "removed-install"
    current_sprite = project / "data/sprite/mika/idle.png"
    current_sprite.parent.mkdir(parents=True)
    current_sprite.write_bytes(b"sprite")
    api = {
        "gpt_sovits_api_path": (old / "data/tts_bundles/installed/gpt").as_posix(),
        "asr_extra_configs": {
            "vosk": {
                "model_path": (
                    old / "assets/system/models/vosk-model-small-cn-0.22"
                ).as_posix()
            }
        },
        "t2i_default_workflow_path": (
            old / "assets/system/workflow/comfy.json"
        ).as_posix(),
    }
    characters = [
        {
            "gpt_model_path": (old / "data/models/mika/model.ckpt").as_posix(),
            "sprites": [
                {
                    "path": (old / "data/sprite/mika/idle.png").as_posix(),
                    "voice_path": (old / "data/speech/mika/idle.wav").as_posix(),
                }
            ],
        }
    ]
    system = {"background_path": (old / "data/backgrounds/room/day.png").as_posix()}
    backgrounds = [
        {
            "sprites": [{"path": (old / "data/backgrounds/room/day.png").as_posix()}],
            "bgm_list": [(old / "data/bgm/room/day.ogg").as_posix()],
        }
    ]
    effects = [{"audio_list": [(old / "data/effects/rain/rain.wav").as_posix()]}]

    changed = _migrate_config_asset_paths(
        root=project,
        api_data=api,
        characters_data=characters,
        system_data=system,
        background_data=backgrounds,
        effect_data=effects,
    )

    assert changed == {"api", "characters", "system", "background", "effect"}
    assert characters[0]["gpt_model_path"] == "data/models/mika/model.ckpt"
    assert characters[0]["sprites"][0] == {
        "path": "data/sprite/mika/idle.png",
        "voice_path": "data/speech/mika/idle.wav",
    }
    assert system["background_path"] == "data/backgrounds/room/day.png"
    assert backgrounds[0]["bgm_list"] == ["data/bgm/room/day.ogg"]
    assert effects[0]["audio_list"] == ["data/effects/rain/rain.wav"]
    assert api["gpt_sovits_api_path"] == "data/tts_bundles/installed/gpt"
    assert api["t2i_default_workflow_path"] == "assets/system/workflow/comfy.json"
    assert api["asr_extra_configs"]["vosk"]["model_path"] == (
        "assets/system/models/vosk-model-small-cn-0.22"
    )


def test_stale_install_media_resources_rebase_to_immutable_asset_references(
    tmp_path,
):
    project = tmp_path / "new-project"
    old = tmp_path / "removed-install"
    characters = [
        {
            "refer_audio_path": (
                old / "assets/system/sound/reference.wav"
            ).as_posix(),
            "sprites": [
                {
                    "path": (old / "assets/present_example.png").as_posix(),
                    "voice_path": (
                        old / "assets/system/sound/voice.wav"
                    ).as_posix(),
                }
            ],
        }
    ]
    system = {
        "background_path": (
            old / "assets/system/picture/background.png"
        ).as_posix(),
        "bgm_path": (old / "assets/system/sound/bgm.ogg").as_posix(),
    }
    backgrounds = [
        {
            "sprites": [
                {
                    "path": (
                        old / "assets/system/picture/room.png"
                    ).as_posix()
                }
            ],
            "bgm_list": [(old / "assets/system/sound/room.ogg").as_posix()],
        }
    ]
    effects = [
        {
            "audio_list": [
                (old / "assets/system/sound/attention.wav").as_posix()
            ]
        }
    ]

    changed = _migrate_config_asset_paths(
        root=project,
        api_data={},
        characters_data=characters,
        system_data=system,
        background_data=backgrounds,
        effect_data=effects,
    )

    assert changed == {"characters", "system", "background", "effect"}
    assert characters[0] == {
        "refer_audio_path": "assets/system/sound/reference.wav",
        "sprites": [
            {
                "path": "assets/present_example.png",
                "voice_path": "assets/system/sound/voice.wav",
            }
        ],
    }
    assert system == {
        "background_path": "assets/system/picture/background.png",
        "bgm_path": "assets/system/sound/bgm.ogg",
    }
    assert backgrounds[0]["sprites"][0]["path"] == (
        "assets/system/picture/room.png"
    )
    assert backgrounds[0]["bgm_list"] == ["assets/system/sound/room.ogg"]
    assert effects[0]["audio_list"] == [
        "assets/system/sound/attention.wav"
    ]


def test_config_path_migration_canonicalizes_known_prefix_case(tmp_path):
    characters = [
        {
            "sprites": [
                {
                    "path": r"DATA\SPRITE\Mika\Idle.png",
                    "voice_path": r"DATA\SPEECH\Mika\Idle.wav",
                }
            ]
        }
    ]
    system = {
        "background_path": r"ASSETS\SYSTEM\PICTURE\Room.png",
        "bgm_path": r"ASSETS\SYSTEM\SOUND\Theme.ogg",
    }

    changed = _migrate_config_asset_paths(
        root=tmp_path,
        api_data={},
        characters_data=characters,
        system_data=system,
        background_data=[],
        effect_data=[],
    )

    assert changed == {"characters", "system"}
    assert characters[0]["sprites"][0] == {
        "path": "data/sprite/Mika/Idle.png",
        "voice_path": "data/speech/Mika/Idle.wav",
    }
    assert system == {
        "background_path": "assets/system/picture/Room.png",
        "bgm_path": "assets/system/sound/Theme.ogg",
    }


def test_config_path_migration_rejects_outer_whitespace_instead_of_retargeting(
    tmp_path,
):
    with pytest.raises(ValueError, match="surrounding whitespace"):
        _migrate_config_asset_paths(
            root=tmp_path,
            api_data={"t2i_default_workflow_path": " data/workflows/comfy.json"},
            characters_data=[],
            system_data={},
            background_data=[],
            effect_data=[],
        )


def test_config_path_migration_canonicalizes_only_the_historical_dot_prefix(
    tmp_path,
):
    api = {
        "asr_extra_configs": {
            "vosk": {"model_path": r".\assets\system\models\vosk-model"}
        }
    }
    system = {
        "music_cover_work_dir": "./data/music_cover",
        "huggingface_cache_dir": "./data/cache/huggingface",
        "music_cover_yt_dlp_exe": r".\tools\yt-dlp.exe",
        "music_cover_ffmpeg_exe": "./tools/ffmpeg",
    }

    changed = _migrate_config_asset_paths(
        root=tmp_path,
        api_data=api,
        characters_data=[],
        system_data=system,
        background_data=[],
        effect_data=[],
    )

    assert changed == {"api", "system"}
    assert api["asr_extra_configs"]["vosk"]["model_path"] == (
        "assets/system/models/vosk-model"
    )
    assert system == {
        "music_cover_work_dir": "data/music_cover",
        "huggingface_cache_dir": "data/cache/huggingface",
        "music_cover_yt_dlp_exe": "tools/yt-dlp.exe",
        "music_cover_ffmpeg_exe": "tools/ffmpeg",
    }


def test_config_path_migration_collapses_only_known_duplicated_storage_prefixes(
    tmp_path,
):
    characters = [
        {
            "sprites": [
                {
                    "path": "data/sprite/mika/sprite/mika/idle.png",
                    "voice_path": "data/speech/mika/speech/mika/idle.wav",
                }
            ]
        }
    ]
    backgrounds = [
        {
            "sprites": [
                {
                    "path": (
                        "data/backgrounds/room/backgrounds/room/day.png"
                    )
                }
            ],
            "bgm_list": ["data/bgm/room/bgm/room/day.ogg"],
        }
    ]
    effects = [
        {
            "audio_list": [
                "data/effects/rain/effects/rain/loop.wav",
            ]
        }
    ]

    changed = _migrate_config_asset_paths(
        root=tmp_path,
        api_data={},
        characters_data=characters,
        system_data={},
        background_data=backgrounds,
        effect_data=effects,
    )

    assert changed == {"characters", "background", "effect"}
    assert characters[0]["sprites"][0] == {
        "path": "data/sprite/mika/idle.png",
        "voice_path": "data/speech/mika/idle.wav",
    }
    assert backgrounds[0]["sprites"][0]["path"] == (
        "data/backgrounds/room/day.png"
    )
    assert backgrounds[0]["bgm_list"] == ["data/bgm/room/day.ogg"]
    assert effects[0]["audio_list"] == ["data/effects/rain/loop.wav"]


def test_config_path_migration_does_not_guess_unrelated_repeated_directories(
    tmp_path,
):
    characters = [
        {
            "sprites": [
                {
                    "path": "data/sprite/mika/archive/mika/idle.png",
                }
            ]
        }
    ]

    changed = _migrate_config_asset_paths(
        root=tmp_path,
        api_data={},
        characters_data=characters,
        system_data={},
        background_data=[],
        effect_data=[],
    )

    assert changed == set()
    assert characters[0]["sprites"][0]["path"] == (
        "data/sprite/mika/archive/mika/idle.png"
    )


@pytest.mark.parametrize(
    "value",
    ["././data/music_cover", "./data/../music_cover", "./data//music_cover"],
)
def test_config_path_migration_rejects_nested_legacy_aliases(tmp_path, value):
    with pytest.raises(ValueError, match="lexical path aliases"):
        _migrate_config_asset_paths(
            root=tmp_path,
            api_data={},
            characters_data=[],
            system_data={"music_cover_work_dir": value},
            background_data=[],
            effect_data=[],
        )


def test_config_path_migration_validates_remote_paths_without_rebasing_them(
    tmp_path,
):
    api = {
        "tts_extra_configs": {
            "kaggle-gpt-sovits": {
                "remote_gpt_model_path": "/kaggle/working/model.ckpt",
                "remote_sovits_model_path": "models/model.pth",
                "remote_ref_audio_path": "/kaggle/working/ref.wav",
            }
        }
    }

    changed = _migrate_config_asset_paths(
        root=tmp_path,
        api_data=api,
        characters_data=[],
        system_data={},
        background_data=[],
        effect_data=[],
    )

    assert changed == set()
    assert api["tts_extra_configs"]["kaggle-gpt-sovits"] == {
        "remote_gpt_model_path": "/kaggle/working/model.ckpt",
        "remote_sovits_model_path": "models/model.pth",
        "remote_ref_audio_path": "/kaggle/working/ref.wav",
    }


def test_config_path_migration_rejects_ambiguous_remote_path_whitespace(tmp_path):
    with pytest.raises(ValueError, match="surrounding whitespace"):
        _migrate_config_asset_paths(
            root=tmp_path,
            api_data={
                "tts_extra_configs": {
                    "kaggle-gpt-sovits": {
                        "remote_ref_audio_path": " /kaggle/working/ref.wav",
                    }
                }
            },
            characters_data=[],
            system_data={},
            background_data=[],
            effect_data=[],
        )


def test_config_path_migration_rejects_remote_lexical_aliases(tmp_path):
    with pytest.raises(ValueError, match="lexical path aliases"):
        _migrate_config_asset_paths(
            root=tmp_path,
            api_data={
                "tts_extra_configs": {
                    "kaggle-gpt-sovits": {
                        "remote_ref_audio_path": "/kaggle/working/./ref.wav",
                    }
                }
            },
            characters_data=[],
            system_data={},
            background_data=[],
            effect_data=[],
        )


def test_existing_external_asset_path_is_not_reclassified_as_project_data(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external/data/models/mika/model.ckpt"
    external.parent.mkdir(parents=True)
    external.write_bytes(b"model")
    characters = [{"gpt_model_path": external.as_posix(), "sprites": []}]

    changed = _migrate_config_asset_paths(
        root=project,
        api_data={},
        characters_data=characters,
        system_data={},
        background_data=[],
        effect_data=[],
    )

    assert changed == set()
    assert characters[0]["gpt_model_path"] == external.as_posix()


def test_config_save_never_guesses_a_missing_external_path_is_project_data(tmp_path):
    external = tmp_path / "offline-disk/data/models/mika/model.ckpt"
    characters = [{"gpt_model_path": external.as_posix(), "sprites": []}]

    _normalize_config_payload_paths("characters", characters, tmp_path / "project")

    assert characters[0]["gpt_model_path"] == external.as_posix()


def test_versioned_config_does_not_repeat_stale_absolute_path_recovery(tmp_path):
    external = tmp_path / "offline-disk/data/models/mika/model.ckpt"
    characters = [{"gpt_model_path": external.as_posix(), "sprites": []}]

    changed = _migrate_config_asset_paths(
        root=tmp_path / "project",
        api_data={},
        characters_data=characters,
        system_data={"path_contract_version": 1},
        background_data=[],
        effect_data=[],
        recover_legacy_absolute=False,
    )

    assert changed == set()
    assert characters[0]["gpt_model_path"] == external.as_posix()


def test_config_load_keeps_missing_relative_assets_repairable_outside_project_cwd(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    config_dir = project / "data" / "config"
    config_dir.mkdir(parents=True)
    unrelated.mkdir()
    paths = {
        "api": config_dir / "api.yaml",
        "characters": config_dir / "characters.yaml",
        "system": config_dir / "system_config.yaml",
        "background": config_dir / "background.yaml",
        "effect": config_dir / "effect.yaml",
    }
    paths["api"].write_text("{}\n", encoding="utf-8")
    paths["system"].write_text("{}\n", encoding="utf-8")
    paths["background"].write_text("[]\n", encoding="utf-8")
    paths["effect"].write_text("[]\n", encoding="utf-8")
    paths["characters"].write_text(
        "- name: Offline\n"
        "  color: '#fff'\n"
        "  sprite_prefix: offline\n"
        "  sprites:\n"
        "    - path: data/sprite/offline/missing.png\n"
        "      voice_path: data/speech/offline/missing.wav\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(unrelated)
    manager = object.__new__(ConfigManager)
    manager._project_root = project
    manager._API_CONFIG_PATH = paths["api"]
    manager._CHARACTERS_CONFIG_PATH = paths["characters"]
    manager._SYSTEM_CONFIG_PATH = paths["system"]
    manager._BACKGOUND_CONFIG_PATH = paths["background"]
    manager._EFFECT_CONFIG_PATH = paths["effect"]

    manager._load_all_configs()

    sprite = manager.config.characters[0].sprites[0]
    sprite_path = sprite.path if hasattr(sprite, "path") else sprite["path"]
    voice_path = sprite.voice_path if hasattr(sprite, "voice_path") else sprite["voice_path"]
    assert sprite_path == "data/sprite/offline/missing.png"
    assert voice_path == "data/speech/offline/missing.wav"


def test_config_migration_publishes_version_marker_only_after_other_files(
    tmp_path,
):
    project = tmp_path / "project"
    config_dir = project / "data/config"
    old_root = tmp_path / "removed-install"
    config_dir.mkdir(parents=True)
    paths = {
        "api": config_dir / "api.yaml",
        "characters": config_dir / "characters.yaml",
        "system": config_dir / "system_config.yaml",
        "background": config_dir / "background.yaml",
        "effect": config_dir / "effect.yaml",
    }
    payloads = {
        paths["api"]: {
            "gpt_sovits_api_path": (
                old_root / "data/tts_bundles/installed/gpt"
            ).as_posix(),
        },
        paths["characters"]: [
            {
                "name": "Offline",
                "color": "#fff",
                "sprite_prefix": "offline",
                "gpt_model_path": (
                    old_root / "data/models/offline/model.ckpt"
                ).as_posix(),
                "sprites": [],
            }
        ],
        paths["system"]: {},
        paths["background"]: [],
        paths["effect"]: [],
    }
    manager = object.__new__(ConfigManager)
    manager._project_root = project
    manager._API_CONFIG_PATH = paths["api"]
    manager._CHARACTERS_CONFIG_PATH = paths["characters"]
    manager._SYSTEM_CONFIG_PATH = paths["system"]
    manager._BACKGOUND_CONFIG_PATH = paths["background"]
    manager._EFFECT_CONFIG_PATH = paths["effect"]
    manager._load_yaml = lambda path: payloads[path]
    attempted: list[str] = []

    def fail_character_write(path, _data):
        attempted.append(path.name)
        if path == paths["characters"]:
            raise OSError("disk full")

    manager._save_single_config = fail_character_write

    with pytest.raises(Exception, match="disk full"):
        manager._load_all_configs()

    assert attempted == ["api.yaml", "characters.yaml"]
    assert "system_config.yaml" not in attempted


def test_stale_external_data_paths_are_not_guessed_to_be_project_assets(tmp_path):
    project = tmp_path / "project"
    old_external = tmp_path / "offline-disk" / "data" / "third-party"
    api = {
        "gpt_sovits_api_path": (old_external / "tts-server").as_posix(),
        "t2i_work_path": (old_external / "ComfyUI").as_posix(),
    }
    system = {
        "chat_ui_theme_path": (old_external / "custom-theme.json").as_posix(),
    }

    changed = _migrate_config_asset_paths(
        root=project,
        api_data=api,
        characters_data=[],
        system_data=system,
        background_data=[],
        effect_data=[],
    )

    assert changed == set()
    assert api["gpt_sovits_api_path"] == (old_external / "tts-server").as_posix()
    assert api["t2i_work_path"] == (old_external / "ComfyUI").as_posix()
    assert system["chat_ui_theme_path"] == (old_external / "custom-theme.json").as_posix()


def test_character_config_write_serializes_current_project_assets_relatively(tmp_path):
    project = tmp_path / "project"
    project_model = project / "data/models/mika/model.ckpt"
    external_model = tmp_path / "external/model.pth"
    project_model.parent.mkdir(parents=True)
    external_model.parent.mkdir(parents=True)
    project_model.write_bytes(b"gpt")
    external_model.write_bytes(b"sovits")
    manager = _config_manager_with_api()
    manager._project_root = project
    manager._CHARACTERS_CONFIG_PATH = project / "data/config/characters.yaml"
    manager.config.characters[0].gpt_model_path = project_model.as_posix()
    manager.config.characters[0].sovits_model_path = external_model.as_posix()
    captured = {}
    manager._save_single_config = lambda _path, data: captured.update(payload=data)

    manager.save_characters_config()

    assert captured["payload"][0]["gpt_model_path"] == "data/models/mika/model.ckpt"
    assert captured["payload"][0]["sovits_model_path"] == external_model.as_posix()


def _save_api_config_for_test(manager: ConfigManager, **overrides) -> str:
    params = {
        "llm_provider": "Deepseek",
        "llm_model": "deepseek-chat",
        "api_key": "sk-test",
        "base_url": "https://api.deepseek.com/v1",
        "is_streaming": "是",
        "tts_provider": "none",
        "sovits_url": "",
        "gpt_sovits_api_path": "",
        "t2i_provider": "comfyui",
        "t2i_url": "http://127.0.0.1:8188",
        "t2i_work_path": "",
        "t2i_default_workflow_path": "",
        "prompt_node_id": "6",
        "output_node_id": "9",
        "temperature": 0.7,
        "repetition_penalty": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "max_context_tokens": 128000,
    }
    params.update(overrides)
    return manager.save_api_config_new(**params)


def test_save_api_config_new_failure_restores_previous_memory_config(monkeypatch):
    manager = _config_manager_with_api()
    previous = manager.config.api_config

    def fail_save():
        raise OSError("disk full")

    monkeypatch.setattr(manager, "save_api_config", fail_save)

    with pytest.raises(OSError, match="disk full"):
        _save_api_config_for_test(manager, llm_model="changed-model")

    assert manager.config.api_config is previous
    assert manager.config.api_config.llm_model["Deepseek"] == "deepseek-chat"


def test_get_llm_api_config_defaults_known_provider_base_url_when_empty():
    manager = _config_manager_with_api(
        llm_provider="Deepseek",
        llm_base_url="   ",
    )

    provider, model, base_url, api_key = manager.get_llm_api_config()

    assert provider == "Deepseek"
    assert model == "deepseek-chat"
    assert base_url == "https://api.deepseek.com/v1"
    assert api_key == "sk-test"


def test_normalize_sprite_voice_types_preserves_explicit_voice_type():
    data = {
        "name": "Mika",
        "sprites": [
            {"path": "sprite.png", "voice_path": "voice.wav", "voice_type": "preset"},
            {"path": "ref.png", "voice_path": "ref.wav", "voice_text": "hello", "voice_type": "reference"},
        ],
    }

    normalized = normalize_sprite_voice_types(data)

    assert normalized["sprites"][0]["voice_type"] == "preset"
    assert normalized["sprites"][1]["voice_type"] == "reference"


def test_normalize_sprite_voice_types_infers_legacy_voice_type_when_missing():
    data = {
        "name": "Mika",
        "sprites": [
            {"path": "sprite.png", "voice_path": "voice.wav"},
            {"path": "ref.png", "voice_path": "ref.wav", "voice_text": "hello"},
        ],
    }

    normalized = normalize_sprite_voice_types(data)

    assert normalized["sprites"][0]["voice_type"] == "fallback"
    assert normalized["sprites"][1]["voice_type"] == "reference"


def test_get_llm_api_config_keeps_saved_base_url():
    manager = _config_manager_with_api(
        llm_provider="Deepseek",
        llm_base_url="https://proxy.example.com/v1",
    )

    _, _, base_url, _ = manager.get_llm_api_config()

    assert base_url == "https://proxy.example.com/v1"


def test_save_api_config_new_persists_token_budget_settings():
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    manager.save_api_config_new(
        "Deepseek",
        "deepseek-chat",
        "sk-test",
        "https://api.deepseek.com/v1",
        "是",
        "none",
        "",
        "",
        "comfyui",
        "http://127.0.0.1:8188",
        "",
        "",
        "6",
        "9",
        0.7,
        1.0,
        0.0,
        0.0,
        128000,
        compact_threshold=0.45,
        compact_target_ratio=0.25,
        history_recent_messages=12,
        max_tool_result_chars=4000,
        max_active_tool_groups=2,
    )

    assert manager.config.api_config.compact_threshold == 0.45
    assert manager.config.api_config.compact_target_ratio == 0.25
    assert manager.config.api_config.history_recent_messages == 12
    assert manager.config.api_config.max_tool_result_chars == 4000
    assert manager.config.api_config.max_active_tool_groups == 2
    assert saved["compact_threshold"] == 0.45
    assert saved["compact_target_ratio"] == 0.25
    assert saved["max_active_tool_groups"] == 2


def test_save_api_config_new_clamps_compact_target_below_threshold():
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    manager.save_api_config_new(
        "Deepseek",
        "deepseek-chat",
        "sk-test",
        "https://api.deepseek.com/v1",
        "是",
        "none",
        "",
        "",
        "comfyui",
        "http://127.0.0.1:8188",
        "",
        "",
        "6",
        "9",
        0.7,
        1.0,
        0.0,
        0.0,
        128000,
        compact_threshold=0.4,
        compact_target_ratio=0.4,
    )

    assert manager.config.api_config.compact_threshold == 0.4
    assert manager.config.api_config.compact_target_ratio == 0.35
    assert saved["compact_target_ratio"] == 0.35


def test_save_api_config_new_rejects_local_tts_without_server_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = _config_manager_with_api()
    manager._project_root = tmp_path
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        tts_provider="gpt-sovits",
        sovits_url="http://127.0.0.1:9880",
        gpt_sovits_api_path="",
    )

    assert "本地 TTS 引擎需要填写服务启动路径" in result
    assert saved == {}


def test_save_api_config_new_rejects_remote_gpt_sovits_without_server_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = _config_manager_with_api()
    manager._project_root = tmp_path
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        tts_provider="gpt-sovits",
        sovits_url="https://example.trycloudflare.com",
        gpt_sovits_api_path="",
    )

    assert "本地 TTS 引擎需要填写服务启动路径" in result
    assert saved == {}


def test_save_api_config_new_defaults_local_tts_path_to_installed_bundle_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    installed_dir = tmp_path / "data" / "tts_bundles" / "installed"
    bundle_root = installed_dir / "gpt_sovits_v2pro" / "GPT-SoVITS-v2pro-20250604"
    bundle_root.mkdir(parents=True)
    (bundle_root / "api_v2.py").write_text("", encoding="utf-8")
    manager = _config_manager_with_api()
    manager._project_root = tmp_path
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)
    expected_path = bundle_root.resolve().as_posix()

    result = _save_api_config_for_test(
        manager,
        tts_provider="gpt-sovits",
        sovits_url="",
        gpt_sovits_api_path="",
    )

    assert result == "API配置已保存！"
    assert manager.config.api_config.gpt_sovits_url == "http://127.0.0.1:9880"
    assert manager.config.api_config.gpt_sovits_api_path == expected_path
    assert saved["gpt_sovits_api_path"] == (
        "data/tts_bundles/installed/gpt_sovits_v2pro/"
        "GPT-SoVITS-v2pro-20250604"
    )


def test_save_api_config_new_rejects_unusable_comfyui_paths_before_mutation(tmp_path):
    manager = _config_manager_with_api()
    manager._project_root = tmp_path
    previous = manager.config.api_config
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        t2i_default_workflow_path="data/workflows/missing.json",
    )

    assert "ComfyUI 默认工作流必须是已存在的文件" in result
    assert manager.config.api_config is previous
    assert saved == {}


def test_save_api_config_new_accepts_project_relative_comfyui_paths(tmp_path):
    workflow = tmp_path / "data" / "workflows" / "sprite.json"
    work_directory = tmp_path / "data" / "comfyui"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    work_directory.mkdir(parents=True)
    manager = _config_manager_with_api()
    manager._project_root = tmp_path
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        t2i_work_path="data/comfyui",
        t2i_default_workflow_path="data/workflows/sprite.json",
    )

    assert result == "API配置已保存！"
    assert saved["t2i_work_path"] == "data/comfyui"
    assert saved["t2i_default_workflow_path"] == "data/workflows/sprite.json"


def test_save_api_config_new_rejects_linked_comfyui_work_directory(tmp_path):
    workflow = tmp_path / "data" / "workflows" / "sprite.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("{}", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    linked_work = tmp_path / "data" / "comfyui"
    try:
        linked_work.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    manager = _config_manager_with_api()
    manager._project_root = tmp_path
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        t2i_work_path="data/comfyui",
        t2i_default_workflow_path="data/workflows/sprite.json",
    )

    assert "symbolic link" in result
    assert saved == {}


def test_save_system_config_applies_network_proxy_environment(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "SOCKS_PROXY",
        "socks_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, name, None)
    monkeypatch.setattr(
        "config.config_manager.apply_mirror_environment",
        lambda _config, **_kwargs: None,
    )
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)
    manager.config.system_config = SystemConfig(
        http_proxy_url="http://127.0.0.1:7890",
        https_proxy_url="http://127.0.0.1:7890",
        mirror_auto_detect_china=False,
        network_proxy_enabled=True,
        socks5_proxy_url="socks5://127.0.0.1:7891",
    )

    manager.save_system_config()

    assert saved["network_proxy_enabled"] is True
    assert saved["http_proxy_url"] == "http://127.0.0.1:7890"
    assert saved["https_proxy_url"] == "http://127.0.0.1:7890"
    assert saved["socks5_proxy_url"] == "socks5://127.0.0.1:7891"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7891"
