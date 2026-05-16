"""Unit tests for character import: sprite paths must be rewritten to the import machine."""

import json
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from tools import file_util


@pytest.fixture
def char_zip_with_sprites():
    """Create a minimal .char ZIP with character.yaml + sprite/ + speech/ files."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        export_root = root / "export"
        export_root.mkdir()

        # ── character.yaml ──
        char_data = {
            "name": "TestChar",
            "color": "#ffffff",
            "sprite_prefix": "test_prefix",
            "sprites": [
                {
                    "path": "data/sprites/test_prefix/happy.png",
                    "voice_path": "data/speech/test_prefix/happy.wav",
                    "voice_text": "hello",
                },
                {
                    "path": "data/sprites/test_prefix/sad.png",
                },
            ],
            "emotion_tags": "1: happy\n2: sad",
            "character_setting": "A test character.",
            "sprite_scale": 1.0,
        }
        yaml_path = export_root / "character.yaml"
        yaml_path.write_text(
            yaml.dump([char_data], allow_unicode=True), encoding="utf-8"
        )

        # ── mock sprite images ──
        sprite_dir = export_root / "sprites" / "test_prefix"
        sprite_dir.mkdir(parents=True)
        (sprite_dir / "happy.png").write_text("fake png")
        (sprite_dir / "sad.png").write_text("fake png")

        # ── mock speech files ──
        speech_dir = export_root / "speech" / "test_prefix"
        speech_dir.mkdir(parents=True)
        (speech_dir / "happy.wav").write_text("fake wav")

        # ── zip it up ──
        zip_path = root / "test_char.char"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in export_root.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(export_root))

        yield zip_path


class TestImportSpritePaths:
    def test_sprite_paths_rewritten_after_import(self, char_zip_with_sprites, tmp_path):
        """Imported sprites must point to the local data/sprite/{prefix}/ dir."""
        dest_data = tmp_path / "data"
        dest_sprite = dest_data / "sprite"
        dest_speech = dest_data / "speech"
        dest_config = dest_data / "config"
        dest_config.mkdir(parents=True)
        characters_yaml = dest_config / "characters.yaml"
        characters_yaml.write_text("[]", encoding="utf-8")

        # Mock global paths
        with (
            mock.patch.object(file_util, "SPRITE_DIR", dest_sprite),
            mock.patch.object(file_util, "SPEECH_DIR", dest_speech),
            mock.patch.object(file_util, "MODEL_DIR", dest_data / "models"),
            mock.patch.object(file_util, "CONFIG_DIR", dest_config),
            mock.patch.object(
                file_util, "CHARACTERS_CONFIG_PATH", characters_yaml
            ),
        ):
            result = file_util.import_character(str(char_zip_with_sprites))
            assert len(result) == 1
            imported = result[0]

            # Verify sprite paths point to local destination
            sprite_paths = [
                s["path"] if isinstance(s, dict) else s.path
                for s in imported.sprites
            ]
            for p in sprite_paths:
                assert "test_prefix" in str(p)
                real = Path(p) if Path(p).is_absolute() else dest_data.parent / p
                assert real.is_file(), f"Sprite file missing: {p}"

            # Verify voice path
            voice_paths = [
                s.get("voice_path") if isinstance(s, dict) else getattr(s, "voice_path", None)
                for s in imported.sprites
            ]
            for vp in voice_paths:
                if vp:
                    real = Path(vp) if Path(vp).is_absolute() else dest_data.parent / vp
                    assert real.is_file(), f"Voice file missing: {vp}"

    def test_sprite_files_actually_copied(self, char_zip_with_sprites, tmp_path):
        """The physical sprite/speech files must exist at the destination."""
        dest_data = tmp_path / "data"
        dest_sprite = dest_data / "sprite"
        dest_speech = dest_data / "speech"
        dest_config = dest_data / "config"
        dest_config.mkdir(parents=True)
        characters_yaml = dest_config / "characters.yaml"
        characters_yaml.write_text("[]", encoding="utf-8")

        with (
            mock.patch.object(file_util, "SPRITE_DIR", dest_sprite),
            mock.patch.object(file_util, "SPEECH_DIR", dest_speech),
            mock.patch.object(file_util, "MODEL_DIR", dest_data / "models"),
            mock.patch.object(file_util, "CONFIG_DIR", dest_config),
            mock.patch.object(
                file_util, "CHARACTERS_CONFIG_PATH", characters_yaml
            ),
        ):
            file_util.import_character(str(char_zip_with_sprites))

        # Check files exist on disk
        assert (dest_sprite / "test_prefix" / "happy.png").is_file()
        assert (dest_sprite / "test_prefix" / "sad.png").is_file()
        assert (dest_speech / "test_prefix" / "happy.wav").is_file()
