"""Portable role resources stay separate from personal conversation data."""

import json
import unittest
import zipfile
import contextlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import yaml

from application.characters.exchange import prepare_character
from config.character_config import CharacterConfig
from config.schema import Character


class ExchangePortableTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[4] / ".tmp-inspect/exchange-tests" / uuid4().hex
        self.root.mkdir(parents=True)
        self.existing = Character(name="Existing", color="#ffffff", sprite_prefix="old", character_setting="keep")
        self.use_case = SimpleNamespace(
            _resource_paths=SimpleNamespace(project_root=self.root),
            _state=SimpleNamespace(character_manager=SimpleNamespace(get_character_name_list=lambda: ["Existing"])),
            _file=lambda value, **_kwargs: Path(value),
            _character=lambda name: self.existing if name == "Existing" else None,
        )

    def package(self, config, files=None):
        path = self.root / f"{uuid4().hex}.char"
        with zipfile.ZipFile(path, "x") as archive:
            archive.writestr("character.yaml", yaml.safe_dump([config]))
            for name, content in (files or {}).items():
                archive.writestr(name, content)
        return path

    def test_audio_only_import_is_a_draft_and_configuration_round_trips(self):
        path = self.package({"name": "Imported", "sprite_prefix": "a", "character_setting": "public", "memory": "private", "cloud": {"key": "secret"}, "emotion_resources": [{"tag": "愤怒", "voice_path": "a.wav", "voice_text": "参考", "voice_lang": "ja", "voice_type": "reference"}]}, {"speech/a/a.wav": b"audio"})
        result = prepare_character(self.use_case, {"path": str(path)})
        character = result["character"]
        self.assertEqual(character["emotion_resources"][0]["tag"], "愤怒")
        self.assertTrue(Path(character["emotion_resources"][0]["voice_path"]).is_file())
        self.assertNotIn("private", json.dumps(character))
        self.assertNotIn("secret", json.dumps(character))
        portable = CharacterConfig.parse_dic(character)
        self.assertEqual(portable.emotion_resources[0]["voice_lang"], "ja")
        self.assertFalse((self.root / "data/config/characters.yaml").exists())

    def test_update_keeps_target_name_and_missing_setting(self):
        path = self.package({"name": "Source", "sprite_prefix": "a"})
        result = prepare_character(self.use_case, {"path": str(path), "targetName": "Existing"})
        self.assertEqual(result["character"]["name"], "Existing")
        self.assertEqual(result["character"]["character_setting"], "keep")
        self.assertEqual(self.existing.sprite_prefix, "old")

    def test_package_traversal_is_rejected_before_extraction(self):
        path = self.package({"name": "A"}, {"../escape": b"bad"})
        with self.assertRaises(ValueError):
            prepare_character(self.use_case, {"path": str(path)})

    def test_native_doki_native_package_round_trip(self):
        doki_root = os.environ.get("DOKI_CHAT_PROJECT_ROOT")
        if not doki_root or not (Path(doki_root) / "server/features/characters/packages.py").is_file():
            self.skipTest("Set DOKI_CHAT_PROJECT_ROOT to run the optional cross-repository round trip")
        sys.path.insert(0, doki_root)
        from server.features.characters.packages import CharacterPackages, inspect_package
        from tools import file_util
        image = self.root / "data/sprite/original/a.png"
        voice = self.root / "data/speech/original/a.wav"
        image.parent.mkdir(parents=True)
        voice.parent.mkdir(parents=True)
        image.write_bytes(b"image")
        voice.write_bytes(b"voice")
        native = CharacterConfig(name="Original", color="#ffffff", sprite_prefix="original", sprites=[{"path": str(image), "voice_path": str(voice), "voice_text": "参考", "voice_type": "reference", "voice_lang": "ja", "tags": ["愤怒"]}], emotion_tags="立绘 1：愤怒", emotion_resources=[{"tag": "温柔", "voice_path": str(voice), "voice_text": "参考", "voice_type": "reference", "voice_lang": "ja"}])
        source = self.root / "native.char"
        previous_directory = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.object(file_util, "SPRITE_DIR", self.root / "data/sprite"), patch.object(file_util, "SPEECH_DIR", self.root / "data/speech"):
                file_util.export_character([native], str(source), open_folder=False)
        finally:
            os.chdir(previous_directory)
        doki = CharacterPackages(self.root / "doki-packages", self.root / "media")
        staged = doki.stage(source)
        role = doki.import_doki(staged["token"], 0)
        self.assertEqual(role["speech"]["local"]["emotions"][0]["label"], "愤怒")
        exported = doki.export_doki(role)
        self.assertEqual(len(inspect_package(exported)[0]["sprites"]), 1)
        returned = prepare_character(self.use_case, {"path": str(exported)})["character"]
        self.assertEqual(returned["sprites"][0]["voice_text"], "参考")
        self.assertEqual(returned["sprites"][0]["tags"], ["愤怒"])
        self.assertTrue(any(e["tag"] == "温柔" for e in returned["emotion_resources"]))


if __name__ == "__main__":
    unittest.main()
