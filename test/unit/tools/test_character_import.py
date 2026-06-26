"""Comprehensive tests for character export/import: sprite paths, voice files, fields."""

import contextlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from tools import file_util


# ── helpers ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _prevent_export_folder_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_open_folder(output_path):
        pytest.fail(f"test attempted to open export folder for {output_path}")

    monkeypatch.setattr(file_util, "_open_export_folder", fail_open_folder)


def _make_export_zip(root: Path, char_data: dict, *,
                     sprites: dict[str, str] | None = None,
                     speeches: dict[str, str] | None = None) -> Path:
    """Create a minimal .char ZIP simulating what export_character produces."""
    export = root / "export"
    export.mkdir()
    (export / "character.yaml").write_text(
        yaml.dump([char_data], allow_unicode=True), encoding="utf-8"
    )
    prefix = char_data.get("sprite_prefix", "pfx")
    if sprites:
        d = export / "sprites" / prefix
        d.mkdir(parents=True)
        for name, content in sprites.items():
            (d / name).write_text(content)
    if speeches:
        d = export / "speech" / prefix
        d.mkdir(parents=True)
        for name, content in speeches.items():
            (d / name).write_text(content)
    zip_path = root / "test.char"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in export.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(export))
    return zip_path


@contextlib.contextmanager
def _mock_dirs(dest_root: Path):
    """Mock file_util globals to use a temp destination."""
    d = dest_root / "data"
    cfg = d / "config"
    cfg.mkdir(parents=True)
    cy = cfg / "characters.yaml"
    cy.write_text("[]", encoding="utf-8")
    patches = [
        mock.patch.object(file_util, "SPRITE_DIR", d / "sprite"),
        mock.patch.object(file_util, "SPEECH_DIR", d / "speech"),
        mock.patch.object(file_util, "MODEL_DIR", d / "models"),
        mock.patch.object(file_util, "CONFIG_DIR", cfg),
        mock.patch.object(file_util, "CHARACTERS_CONFIG_PATH", cy),
    ]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


# ── base data ───────────────────────────────────────────────────────────────

BASIC_CHAR = {
    "name": "Alice",
    "color": "#ff0000",
    "sprite_prefix": "alice",
    "sprite_scale": 1.5,
    "speech_speed": 1.2,
    "speech_volume": 0.8,
    "pronunciation_map": {"Alice": "アリス"},
    "sprites": [
        {"path": "smile.png", "voice_path": "greet.wav", "voice_text": "hello"},
        {"path": "angry.png"},
    ],
    "emotion_tags": "1: smile\n2: angry",
    "character_setting": "A girl.",
    "prompt_text": "hi",
    "prompt_lang": "ja",
    "gpt_model_path": None,
    "sovits_model_path": None,
    "refer_audio_path": None,
}


# ── Import tests ────────────────────────────────────────────────────────────

class TestImport:
    def test_character_config_parse_normalizes_voice_without_text_to_fallback(self):
        from config.character_config import CharacterConfig

        data = dict(BASIC_CHAR)
        data["sprites"] = [{"path": "smile.png", "voice_path": "greet.wav", "voice_type": "preset"}]

        result = CharacterConfig.parse_dic(data)

        assert result.sprites[0]["voice_type"] == "fallback"

    def test_sprite_paths_rewritten(self, tmp_path):
        """Imported sprite paths point to the local data/sprite/{prefix}/ dir."""
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), BASIC_CHAR,
                                 sprites={"smile.png": "png", "angry.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        c = result[0]
        for s in c.sprites:
            p = Path(s["path"])
            assert "alice" in str(p)
            assert p.is_file(), f"missing: {p}"

    def test_voice_restored_to_speech_dir(self, tmp_path):
        """Voice files land in data/speech/{prefix}/."""
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), BASIC_CHAR,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                file_util.import_character(str(z))
                assert (file_util.SPEECH_DIR / "alice" / "greet.wav").is_file()

    def test_voice_path_points_correctly(self, tmp_path):
        """voice_path in the sprite data points to the restored file."""
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), BASIC_CHAR,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        vp = result[0].sprites[0].get("voice_path")
        assert vp
        assert Path(vp).is_file()

    def test_old_voice_with_voice_text_without_voice_type_imports_as_reference(self, tmp_path):
        """Old character packages used voice_text to mark reference voice semantics."""
        data = dict(BASIC_CHAR)
        data["sprites"] = [{"path": "smile.png", "voice_path": "greet.wav", "voice_text": "hello"}]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(
                Path(td),
                data,
                sprites={"smile.png": "png"},
                speeches={"greet.wav": "wav"},
            )
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))

        assert result[0].sprites[0]["voice_type"] == "reference"

    def test_old_voice_without_voice_text_or_voice_type_imports_as_fallback(self, tmp_path):
        """Old character packages without reference text are fallback sprite voices."""
        data = dict(BASIC_CHAR)
        data["sprites"] = [{"path": "smile.png", "voice_path": "greet.wav"}]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(
                Path(td),
                data,
                sprites={"smile.png": "png"},
                speeches={"greet.wav": "wav"},
            )
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))

        assert result[0].sprites[0]["voice_type"] == "fallback"

    def test_fields_preserved(self, tmp_path):
        """Name, sprite_scale, emotion_tags, voice_text etc. survive import."""
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), BASIC_CHAR,
                                 sprites={"smile.png": "png", "angry.png": "png"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        c = result[0]
        assert c.name == "Alice"
        assert c.sprite_scale == 1.5
        assert c.emotion_tags == "1: smile\n2: angry"
        assert c.character_setting == "A girl."
        assert c.prompt_lang == "ja"
        assert len(c.sprites) == 2
        assert c.sprites[0]["voice_text"] == "hello"
        assert "angry.png" in c.sprites[1]["path"]

    def test_name_conflict_renames(self, tmp_path):
        """Duplicate name gets a suffix like 'Alice（1）'."""
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), BASIC_CHAR,
                                 sprites={"smile.png": "png"})
            with _mock_dirs(tmp_path):
                # Write pre-existing Alice into the mocked characters.yaml
                file_util.CHARACTERS_CONFIG_PATH.write_text(yaml.dump(
                    [{"name": "Alice", "color": "#000", "sprite_prefix": "x"}],
                    allow_unicode=True,
                ), encoding="utf-8")
                result = file_util.import_character(str(z))
                assert result[0].name != "Alice"
                assert "Alice" in result[0].name

    def test_sprite_prefix_conflict_renames(self, tmp_path):
        """Duplicate prefix gets a suffix; files go to the new directory."""
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), BASIC_CHAR,
                                 sprites={"smile.png": "png"})
            with _mock_dirs(tmp_path):
                # Write pre-existing alice prefix into mocked config
                file_util.CHARACTERS_CONFIG_PATH.write_text(yaml.dump(
                    [{"name": "Bob", "color": "#000", "sprite_prefix": "alice"}],
                    allow_unicode=True,
                ), encoding="utf-8")
                result = file_util.import_character(str(z))
                c = result[0]
                assert c.sprite_prefix != "alice"
                assert "alice" in c.sprite_prefix
                assert (file_util.SPRITE_DIR / c.sprite_prefix / "smile.png").is_file()

    def test_import_without_sprites(self, tmp_path):
        """Character with empty sprites imports without errors."""
        data = dict(BASIC_CHAR, sprites=[])
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), data)
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        assert result[0].sprites == []

    def test_import_without_voice(self, tmp_path):
        """Character with sprites but no speech dir imports fine."""
        data = dict(BASIC_CHAR, sprites=[{"path": "only.png"}])
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), data,
                                 sprites={"only.png": "png"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        assert len(result[0].sprites) == 1
        assert Path(result[0].sprites[0]["path"]).is_file()


# ── Export tests ────────────────────────────────────────────────────────────

class TestExport:
    def test_sprite_paths_are_filenames_only(self, tmp_path):
        """Export rewrites sprite paths to just the filename."""
        with _mock_dirs(tmp_path):
            out = _run_export(BASIC_CHAR, tmp_path)
        with zipfile.ZipFile(out, "r") as zf:
            yaml_data = yaml.safe_load(zf.read("character.yaml"))
        sprites = yaml_data[0]["sprites"]
        assert sprites[0]["path"] == "smile.png"
        assert sprites[1]["path"] == "angry.png"

    def test_voice_paths_are_filenames_only_without_mutating_config(self, tmp_path):
        """Export rewrites YAML voice paths without changing the source config."""
        voice_path = str((tmp_path / "data" / "speech" / "alice" / "greet.wav").resolve())
        data = dict(BASIC_CHAR)
        data["sprites"] = [
            {"path": "smile.png", "voice_path": voice_path, "voice_text": "hello"},
        ]

        with _mock_dirs(tmp_path):
            out = _run_export(data, tmp_path)
        with zipfile.ZipFile(out, "r") as zf:
            yaml_data = yaml.safe_load(zf.read("character.yaml"))

        assert yaml_data[0]["sprites"][0]["voice_path"] == "greet.wav"
        assert data["sprites"][0]["voice_path"] == voice_path

    def test_missing_fields_included(self, tmp_path):
        """pronunciation_map, speech_speed, speech_volume must be in YAML."""
        with _mock_dirs(tmp_path):
            out = _run_export(BASIC_CHAR, tmp_path)
        with zipfile.ZipFile(out, "r") as zf:
            yaml_data = yaml.safe_load(zf.read("character.yaml"))
        c = yaml_data[0]
        assert c["speech_speed"] == 1.2
        assert c["speech_volume"] == 0.8
        assert c["pronunciation_map"] == {"Alice": "アリス"}

    def test_sprite_files_in_zip(self, tmp_path):
        """Sprite PNG files are inside the ZIP."""
        with _mock_dirs(tmp_path):
            # create dummy files under the mocked sprite dir
            sm = file_util.SPRITE_DIR / "alice"
            sm.mkdir(parents=True)
            (sm / "smile.png").write_text("fake")
            (sm / "angry.png").write_text("fake")
            out = str(tmp_path / "out.char")
            _run_export(BASIC_CHAR, tmp_path, output=out)
        with zipfile.ZipFile(out, "r") as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
        assert any("alice/smile.png" in n for n in names)
        assert any("alice/angry.png" in n for n in names)

    def test_voice_files_in_zip(self, tmp_path):
        """Speech files are inside the ZIP."""
        with _mock_dirs(tmp_path):
            sp = file_util.SPEECH_DIR / "alice"
            sp.mkdir(parents=True)
            (sp / "greet.wav").write_text("fake")
            out = str(tmp_path / "out.char")
            _run_export(BASIC_CHAR, tmp_path, output=out)
        with zipfile.ZipFile(out, "r") as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
        assert any("alice/greet.wav" in n for n in names)

    def test_manifest_json_created(self, tmp_path):
        """Export produces a manifest.json."""
        with _mock_dirs(tmp_path):
            out = _run_export(BASIC_CHAR, tmp_path)
        with zipfile.ZipFile(out, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert "original_paths" in manifest

    def test_export_accepts_open_folder_false(self, tmp_path, monkeypatch):
        """React bridge exports should not open a native folder."""
        from config.character_config import CharacterConfig

        def fail_open_folder(output_path):
            pytest.fail(f"export opened folder for {output_path}")

        monkeypatch.setattr(file_util, "_open_export_folder", fail_open_folder)
        cc = CharacterConfig.parse_dic(char_data=BASIC_CHAR)
        output = tmp_path / "out.char"

        with _mock_dirs(tmp_path):
            file_util.export_character([cc], str(output), open_folder=False)

        assert output.is_file()


def _run_export(char_data: dict, tmp_path: Path, output: str | None = None) -> str:
    """Export a CharacterConfig and return the path."""
    from config.character_config import CharacterConfig
    cc = CharacterConfig.parse_dic(char_data=char_data)
    out = output or str(tmp_path / "out.char")
    file_util.export_character([cc], out, open_folder=False)
    return out


# ── Backward compat ─────────────────────────────────────────────────────────

class TestBackwardCompat:
    """Old export formats (full paths in sprite.path) must still import correctly."""

    def test_old_relative_paths(self, tmp_path):
        """Sprite paths like 'data/sprites/alice/smile.png' from old exports."""
        old = dict(BASIC_CHAR)
        old["sprites"] = [
            {"path": "data/sprites/alice/smile.png",
             "voice_path": "data/speech/alice/greet.wav", "voice_text": "hi"},
        ]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        c = result[0]
        assert Path(c.sprites[0]["path"]).is_file()
        vp = c.sprites[0].get("voice_path")
        assert vp and Path(vp).is_file()

    def test_old_absolute_paths(self, tmp_path):
        """Sprite paths like 'C:\\...\\data\\sprites\\alice\\smile.png' from old exports."""
        old = dict(BASIC_CHAR)
        fake_abs = str(Path("C:/somewhere/data/sprites/alice/smile.png"))
        old["sprites"] = [{"path": fake_abs}]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        assert Path(result[0].sprites[0]["path"]).is_file()

    def test_old_posix_absolute_sprite_path(self, tmp_path):
        """Sprite paths like '/opt/app/data/sprite/alice/smile.png' from old exports."""
        old = dict(BASIC_CHAR)
        old["sprites"] = [{"path": "/opt/app/data/sprite/alice/smile.png"}]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        assert Path(result[0].sprites[0]["path"]).is_file()

    def test_old_absolute_voice_path(self, tmp_path):
        """voice_path with a legacy absolute host path resolves to restored speech."""
        old = dict(BASIC_CHAR)
        old["sprites"] = [
            {"path": "smile.png",
             "voice_path": "C:\\somewhere\\data\\speech\\alice\\greet.wav",
             "voice_text": "hi"},
        ]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        vp = result[0].sprites[0].get("voice_path")
        assert vp and Path(vp).is_file()
        assert Path(vp).name == "greet.wav"

    @pytest.mark.parametrize(
        ("field", "bad_path"),
        [
            ("path", "../evil.png"),
            ("path", "bad\0.png"),
            ("path", "/tmp/C:evil.png"),
            ("voice_path", "../evil.wav"),
            ("voice_path", "/opt/app/../evil.wav"),
            ("voice_path", "C:\\tmp\\C:evil.wav"),
        ],
    )
    def test_rejects_unsafe_sprite_or_voice_paths(self, tmp_path, field, bad_path):
        """Relaxed legacy paths must still reject traversal and NUL bytes."""
        old = dict(BASIC_CHAR)
        sprite = {"path": "smile.png"}
        sprite[field] = bad_path
        old["sprites"] = [sprite]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"})
            with _mock_dirs(tmp_path), pytest.raises(ValueError):
                file_util.import_character(str(z))

    def test_empty_prefix_drops_legacy_absolute_host_paths(self, tmp_path):
        """Characters without a prefix still must not keep host absolute paths."""
        old = dict(BASIC_CHAR)
        old["sprite_prefix"] = ""
        old["sprites"] = [
            {
                "path": "/opt/app/data/sprite/alice/smile.png",
                "voice_path": "C:\\somewhere\\data\\speech\\alice\\greet.wav",
                "voice_text": "hi",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        sprite = result[0].sprites[0]
        assert sprite["path"] == "smile.png"
        assert sprite["voice_path"] == "greet.wav"

    def test_legacy_absolute_paths_follow_renamed_sprite_prefix(self, tmp_path):
        """Legacy paths are rebuilt under the conflict-resolved prefix."""
        old = dict(BASIC_CHAR)
        old["sprites"] = [
            {
                "path": "C:\\somewhere\\data\\sprite\\alice\\smile.png",
                "voice_path": "C:\\somewhere\\data\\speech\\alice\\greet.wav",
                "voice_text": "hi",
            },
        ]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                file_util.CHARACTERS_CONFIG_PATH.write_text(yaml.dump(
                    [{"name": "Bob", "color": "#000", "sprite_prefix": "alice"}],
                    allow_unicode=True,
                ), encoding="utf-8")
                result = file_util.import_character(str(z))

        c = result[0]
        assert c.sprite_prefix != "alice"
        assert Path(c.sprites[0]["path"]).parent.name == c.sprite_prefix
        assert Path(c.sprites[0]["voice_path"]).parent.name == c.sprite_prefix
        assert Path(c.sprites[0]["path"]).is_file()
        assert Path(c.sprites[0]["voice_path"]).is_file()

    def test_old_voice_from_voices_dir(self, tmp_path):
        """voice_path pointing to 'data/voices/...' (old upload_voice dir)."""
        old = dict(BASIC_CHAR)
        old["sprites"] = [
            {"path": "smile.png",
             "voice_path": "data/voices/alice/greet.wav", "voice_text": "hi"},
        ]
        with tempfile.TemporaryDirectory() as td:
            z = _make_export_zip(Path(td), old,
                                 sprites={"smile.png": "png"},
                                 speeches={"greet.wav": "wav"})
            with _mock_dirs(tmp_path):
                result = file_util.import_character(str(z))
        vp = result[0].sprites[0].get("voice_path")
        assert vp and Path(vp).is_file()
        # Should be restored to speech/ not voices/
        assert "speech" in str(vp).replace("\\", "/")


# ── Round-trip ──────────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_export_then_import(self, tmp_path):
        """Export a character, then import it back; data must match."""
        from config.character_config import CharacterConfig

        with _mock_dirs(tmp_path):
            # create real files under mocked dirs
            sm = file_util.SPRITE_DIR / "alice"
            sp = file_util.SPEECH_DIR / "alice"
            sm.mkdir(parents=True)
            sp.mkdir(parents=True)
            (sm / "smile.png").write_text("png1")
            (sm / "angry.png").write_text("png2")
            (sp / "greet.wav").write_text("wav1")

            cc = CharacterConfig.parse_dic(char_data=BASIC_CHAR)
            out = str(tmp_path / "roundtrip.char")
            file_util.export_character([cc], out, open_folder=False)

            # Import to same mocked destination
            result = file_util.import_character(out)

            c = result[0]
            assert c.name == "Alice"
            assert c.sprite_prefix == "alice"
            assert c.sprite_scale == 1.5
            assert len(c.sprites) == 2
            assert (file_util.SPRITE_DIR / "alice" / "smile.png").is_file()
            assert (file_util.SPEECH_DIR / "alice" / "greet.wav").is_file()
            vp = c.sprites[0].get("voice_path")
            assert vp and Path(vp).is_file()
