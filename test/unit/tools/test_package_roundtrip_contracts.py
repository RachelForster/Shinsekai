"""Exhaustive field contracts and UseCase end-to-end import/export round-trip tests."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from PIL import Image
import pytest
import yaml

from application.backgrounds import (
    BackgroundExportResult,
    BackgroundOperation,
    BackgroundUseCase,
    parse_background_request,
)
from application.characters import (
    CharacterExportResult,
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
)
from application.effects import (
    EffectExportResult,
    EffectOperation,
    EffectRequest,
    EffectUseCase,
)
from config.character_manager import CharacterManager
from config.schema import (
    Background,
    Character,
    Effect,
    ModelSprites,
    PortraitCrop,
    RelationGraph,
    Sprite,
    SpriteTransition,
)
from config.sprite_files import sprite_fingerprint
from config.sprite_mouth import correction
from core.media.avatar.registry import configure_builtin_formats
from core.sprite.transitions import valid_transitions
from tools import file_util


RESERVED_CHARACTER_FIELDS = frozenset({"id", "display_name", "is_builtin", "pinned", "undeletable"})
RESERVED_BACKGROUND_FIELDS = frozenset({"id"})
RESERVED_EFFECT_FIELDS = frozenset({"id"})


@pytest.fixture(autouse=True)
def _prevent_export_folder_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_open_folder(output_path):
        pytest.fail(f"test attempted to open export folder for {output_path}")

    monkeypatch.setattr(file_util, "_open_export_folder", fail_open_folder)


@contextlib.contextmanager
def _isolated_file_util_workspace(root: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = root / "data"
    config_dir = data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    characters_yaml = config_dir / "characters.yaml"
    if not characters_yaml.exists():
        characters_yaml.write_text("[]\n", encoding="utf-8")
    background_yaml = config_dir / "background.yaml"
    if not background_yaml.exists():
        background_yaml.write_text("[]\n", encoding="utf-8")
    effect_yaml = config_dir / "effect.yaml"
    if not effect_yaml.exists():
        effect_yaml.write_text("[]\n", encoding="utf-8")

    monkeypatch.chdir(root)
    monkeypatch.setattr(file_util, "BASE_DATA_PATH", data_dir)
    monkeypatch.setattr(file_util, "SPRITE_DIR", data_dir / "sprite")
    monkeypatch.setattr(file_util, "SPEECH_DIR", data_dir / "speech")
    monkeypatch.setattr(file_util, "MODEL_DIR", data_dir / "models")
    monkeypatch.setattr(file_util, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(file_util, "CHARACTERS_CONFIG_PATH", characters_yaml)
    monkeypatch.setattr(file_util, "BACKGROUND_CONFIG_PATH", background_yaml)
    monkeypatch.setattr(file_util, "BACKGROUND_UPLOAD_DIR", data_dir / "backgrounds")
    monkeypatch.setattr(file_util, "BGM_UPLOAD_DIR", data_dir / "bgm")
    yield {
        "data_dir": data_dir,
        "characters_yaml": characters_yaml,
        "background_yaml": background_yaml,
        "effect_yaml": effect_yaml,
    }


class _YamlBackedConfigManager:
    def __init__(
        self,
        *,
        characters_yaml: Path | None = None,
        background_yaml: Path | None = None,
        effect_yaml: Path | None = None,
        characters: list[Character] = (),
        backgrounds: list[Background] = (),
        effects: list[Effect] = (),
    ) -> None:
        self._characters_yaml = characters_yaml
        self._background_yaml = background_yaml
        self._effect_yaml = effect_yaml
        self.config = SimpleNamespace(
            api_config=SimpleNamespace(tts_provider="none"),
            characters=list(characters),
            background_list=list(backgrounds),
            effect_list=list(effects),
        )

    def get_character_by_name(self, name: str) -> Character | None:
        return next(
            (item for item in self.config.characters if item.name.lower() == name.lower()),
            None,
        )

    def get_background_by_name(self, name: str) -> Background | None:
        return next(
            (item for item in self.config.background_list if item.name.lower() == name.lower()),
            None,
        )

    def get_effect_by_name(self, name: str) -> Effect | None:
        return next(
            (item for item in self.config.effect_list if item.name.lower() == name.lower()),
            None,
        )

    def save_characters_config(self) -> None:
        if self._characters_yaml is None:
            return
        payload = [item.model_dump(mode="json", by_alias=True) for item in self.config.characters]
        self._characters_yaml.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def save_background_config(self) -> None:
        if self._background_yaml is None:
            return
        payload = [item.model_dump(mode="json", by_alias=True) for item in self.config.background_list]
        self._background_yaml.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def save_effect_config(self) -> None:
        if self._effect_yaml is None:
            return
        payload = [item.model_dump(mode="json", by_alias=True) for item in self.config.effect_list]
        self._effect_yaml.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def reload(self) -> None:
        if self._characters_yaml is not None and self._characters_yaml.is_file():
            raw = yaml.safe_load(self._characters_yaml.read_text(encoding="utf-8")) or []
            self.config.characters = [Character.model_validate(item) for item in raw]
        if self._background_yaml is not None and self._background_yaml.is_file():
            raw = yaml.safe_load(self._background_yaml.read_text(encoding="utf-8")) or []
            self.config.background_list = [Background.model_validate(item) for item in raw]
        if self._effect_yaml is not None and self._effect_yaml.is_file():
            raw = yaml.safe_load(self._effect_yaml.read_text(encoding="utf-8")) or []
            self.config.effect_list = [Effect.model_validate(item) for item in raw]


def _write_mouth_bundle(directory: Path, source: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for pose in ("closed", "half", "open"):
        Image.new("RGBA", (12, 8), (220, 150, 160, 220)).save(directory / f"mouth-{pose}.png")
    Image.new("RGB", (64, 64), "white").save(directory / "reference.png")
    manifest = {
        "version": 1,
        "sourceFingerprint": sprite_fingerprint(source),
        "width": 64,
        "height": 64,
        "fps": 0,
        "duration": 0,
        "patchBox": [16, 20, 48, 44],
        "mouths": {pose: f"mouth-{pose}.png" for pose in ("closed", "half", "open")},
        "track": [{"time": 0, "matrix": [1, 0, 0, 1, 0, 0]}],
        "correction": correction({"offsetX": 2, "scale": 1.1}),
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _build_full_character_fixture(src: Path) -> tuple[Character, dict[str, bytes]]:
    prefix = "alice"
    sprite_dir = src / "data" / "sprite" / prefix
    speech_dir = src / "data" / "speech" / prefix
    model_dir = src / "data" / "models" / prefix
    l2d_dir = sprite_dir / "avatars" / "l2d" / "original"
    transitions_dir = sprite_dir / "transitions"
    for directory in (sprite_dir, speech_dir, model_dir, l2d_dir, transitions_dir):
        directory.mkdir(parents=True, exist_ok=True)

    smile_png = sprite_dir / "smile.png"
    angry_png = sprite_dir / "angry.png"
    Image.new("RGBA", (64, 64), (255, 120, 180, 255)).save(smile_png)
    Image.new("RGBA", (64, 64), (100, 140, 255, 255)).save(angry_png)

    smile_wav = speech_dir / "smile.wav"
    angry_wav = speech_dir / "angry.wav"
    smile_wav.write_bytes(b"RIFF-smile-wav")
    angry_wav.write_bytes(b"RIFF-angry-wav")

    mouth_manifest = _write_mouth_bundle(sprite_dir / "mouth-sync" / "smile", smile_png)

    transition_webm = transitions_dir / "smile_to_angry.webm"
    transition_webm.write_bytes(b"WEBM-alpha-transition-clip")

    l2d_model = l2d_dir / "alice.model3.json"
    l2d_model.write_text(
        json.dumps({"Version": 3, "FileReferences": {"Moc": "alice.moc3", "Textures": ["tex.png"]}}),
        encoding="utf-8",
    )
    (l2d_dir / "alice.moc3").write_bytes(b"MOC3-binary-payload")
    (l2d_dir / "tex.png").write_bytes(b"PNG-l2d-texture")
    l2d_state = l2d_dir / "happy.json"
    l2d_state.write_text(json.dumps({"parameters": {"ParamAngleX": 12}, "expressions": [], "motion": ""}), encoding="utf-8")
    l2d_voice = l2d_dir / "happy.wav"
    l2d_voice.write_bytes(b"RIFF-l2d-voice")

    gpt_ckpt = model_dir / "alice-gpt.ckpt"
    sovits_pth = model_dir / "alice-sovits.pth"
    refer_wav = model_dir / "alice-refer.wav"
    gpt_ckpt.write_bytes(b"GPT-CKPT-BYTES")
    sovits_pth.write_bytes(b"SOVITS-PTH-BYTES")
    refer_wav.write_bytes(b"REFER-WAV-BYTES")

    character_payload = {
        "name": "Alice",
        "color": "#ff66aa",
        "sprite_prefix": prefix,
        "sprites": [
            {
                "path": str(smile_png),
                "voice_path": str(smile_wav),
                "voice_text": "Hello, nice to meet you!",
                "voice_type": "preset",
                "portrait_crop": {"x": 0.25, "y": 0.35, "zoom": 2.5},
                "mouth_sync": str(mouth_manifest),
                "group": "校服",
            },
            {
                "path": str(angry_png),
                "voice_path": str(angry_wav),
                "voice_text": "Hmph!",
                "voice_type": "reference",
                "portrait_crop": {"x": 0.6, "y": 0.4, "zoom": 1.8},
                "mouth_sync": None,
                "group": "校服",
            },
        ],
        "sprite_transitions": [
            {
                "from_path": str(smile_png),
                "to_path": str(angry_png),
                "path": str(transition_webm),
                "from_fingerprint": sprite_fingerprint(smile_png),
                "to_fingerprint": sprite_fingerprint(angry_png),
                "frame_count": 22,
                "h3_resolution": "hd",
            }
        ],
        "character_brief": "Cheerful club president.",
        "relation_graph": {
            "nodes": [{"key": "Alice"}, {"key": "Bob"}],
            "edges": [
                {"source": "Alice", "target": "Bob", "temperature": 7, "content": "Best friend"},
                {"source": "Bob", "target": "Alice", "temperature": 5, "content": "Classmate"},
            ],
        },
        "character_setting": "Detailed personality and background setting.",
        "sprite_scale": 1.35,
        "portrait_crop": {"x": 0.35, "y": 0.45, "zoom": 2.2},
        "portrait_sprite_index": 1,
        "emotion_tags": "立绘 1：smile\n立绘 2：angry\n",
        "sprite_groups": ["校服", "私服"],
        "default_sprite_group": "校服",
        "fallback_to_default_group": False,
        "avatar_type": "l2d",
        "avatars": {
            "l2d": {
                "model_path": str(l2d_model),
                "sprites": [
                    {
                        "path": str(l2d_state),
                        "voice_path": str(l2d_voice),
                        "voice_text": "L2D happy line",
                        "voice_type": "preset",
                        "portrait_crop": {"x": 0.2, "y": 0.3, "zoom": 1.5},
                        "mouth_sync": None,
                        "group": "演出",
                    }
                ],
                "emotion_tags": "立绘 1：happy\n",
            },
            "future": {
                "model_path": "models/alice/future.vrm",
                "sprites": [],
                "emotion_tags": "1: future",
            },
        },
        "gpt_model_path": str(gpt_ckpt),
        "sovits_model_path": str(sovits_pth),
        "refer_audio_path": str(refer_wav),
        "prompt_text": "Reference audio transcript.",
        "prompt_lang": "ja",
        "speech_speed": 1.15,
        "speech_volume": 0.85,
        "pronunciation_map": {"Alice": "アリス"},
    }

    assert set(character_payload) == set(Character.model_fields) - RESERVED_CHARACTER_FIELDS
    assert set(character_payload["sprites"][0]) == set(Sprite.model_fields)
    assert set(character_payload["sprite_transitions"][0]) == set(SpriteTransition.model_fields)
    assert set(character_payload["avatars"]["l2d"]) == set(ModelSprites.model_fields)

    expected_bytes = {
        "smile.png": smile_png.read_bytes(),
        "angry.png": angry_png.read_bytes(),
        "smile.wav": smile_wav.read_bytes(),
        "angry.wav": angry_wav.read_bytes(),
        "mouth_manifest": mouth_manifest.read_bytes(),
        "transition.webm": transition_webm.read_bytes(),
        "l2d_model": l2d_model.read_bytes(),
        "l2d_moc3": (l2d_dir / "alice.moc3").read_bytes(),
        "l2d_tex": (l2d_dir / "tex.png").read_bytes(),
        "l2d_state": l2d_state.read_bytes(),
        "l2d_voice": l2d_voice.read_bytes(),
        "gpt_ckpt": gpt_ckpt.read_bytes(),
        "sovits_pth": sovits_pth.read_bytes(),
        "refer_wav": refer_wav.read_bytes(),
    }
    return Character.model_validate(character_payload), expected_bytes


# ── Schema Exhaustiveness Guards ───────────────────────────────────────────


def test_schema_field_sets_match_roundtrip_contract_expectations() -> None:
    assert set(Character.model_fields) - RESERVED_CHARACTER_FIELDS == {
        "name",
        "color",
        "sprite_prefix",
        "sprites",
        "sprite_transitions",
        "character_brief",
        "relation_graph",
        "character_setting",
        "sprite_scale",
        "portrait_crop",
        "portrait_sprite_index",
        "emotion_tags",
        "sprite_groups",
        "default_sprite_group",
        "fallback_to_default_group",
        "avatar_type",
        "avatars",
        "gpt_model_path",
        "sovits_model_path",
        "refer_audio_path",
        "prompt_text",
        "prompt_lang",
        "speech_speed",
        "speech_volume",
        "pronunciation_map",
    }
    assert set(Sprite.model_fields) == {
        "path",
        "voice_path",
        "voice_text",
        "voice_type",
        "portrait_crop",
        "mouth_sync",
        "group",
    }
    assert set(ModelSprites.model_fields) == {"model_path", "sprites", "emotion_tags"}
    assert set(SpriteTransition.model_fields) == {
        "from_path",
        "to_path",
        "path",
        "from_fingerprint",
        "to_fingerprint",
        "frame_count",
        "h3_resolution",
    }
    assert set(Background.model_fields) - RESERVED_BACKGROUND_FIELDS == {
        "name",
        "sprite_prefix",
        "sprites",
        "bg_tags",
        "bgm_list",
        "bgm_tags",
    }
    assert set(Effect.model_fields) - RESERVED_EFFECT_FIELDS == {
        "name",
        "color",
        "prompt_text",
        "audio_list",
        "audio_tags",
        "image_list",
        "image_tags",
        "image_audio_list",
        "ambient_list",
        "ambient_tags",
        "ambient_audio_list",
        "ambient_layers",
    }


# ── CharacterUseCase End-to-End Round-Trip ─────────────────────────────────


def test_character_use_case_export_import_preserves_every_field_and_conflict_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_builtin_formats()
    monkeypatch.setattr("core.media.alpha_video.verify_alpha_video", lambda _path: 22)

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()

    with _isolated_file_util_workspace(src, monkeypatch) as src_paths:
        source_char, expected_bytes = _build_full_character_fixture(src)
        src_cfg = _YamlBackedConfigManager(
            characters_yaml=src_paths["characters_yaml"],
            characters=[source_char],
        )
        src_cfg.save_characters_config()
        src_mgr = CharacterManager.__new__(CharacterManager)
        src_mgr._config_manager = src_cfg
        src_state = SimpleNamespace(
            config_manager=src_cfg,
            character_manager=src_mgr,
            project_root_dir=str(src),
            template_dir_path=str(src / "data" / "character_templates"),
        )
        src_uc = CharacterUseCase(src_state, file_access_roots=(src,))
        export_result = src_uc.execute(
            parse_character_request(CharacterOperation.EXPORT, {"name": "Alice"})
        )
        assert isinstance(export_result, CharacterExportResult)
        archive_path = (src / export_result.path).resolve()
        assert archive_path.is_file()

    with _isolated_file_util_workspace(dst, monkeypatch) as dst_paths:
        dst_cfg = _YamlBackedConfigManager(characters_yaml=dst_paths["characters_yaml"])
        dst_mgr = CharacterManager.__new__(CharacterManager)
        dst_mgr._config_manager = dst_cfg
        dst_state = SimpleNamespace(
            config_manager=dst_cfg,
            character_manager=dst_mgr,
            project_root_dir=str(dst),
            template_dir_path=str(dst / "data" / "character_templates"),
        )
        dst_uc = CharacterUseCase(dst_state, file_access_roots=(src, dst))

        # 1) Clean import into destination workspace
        first_imported = dst_uc.execute(
            parse_character_request(CharacterOperation.IMPORT, {"paths": [str(archive_path)]})
        )
        assert len(first_imported) == 1
        assert len(dst_cfg.config.characters) == 1
        char1 = dst_cfg.config.characters[0]

        def _assert_character_preserved(
            imported: Character,
            *,
            expected_name: str,
            expected_prefix: str,
        ) -> None:
            assert imported.name == expected_name
            assert imported.sprite_prefix == expected_prefix
            assert imported.color == "#ff66aa"
            assert imported.character_brief == "Cheerful club president."
            assert imported.character_setting == "Detailed personality and background setting."
            assert imported.sprite_scale == 1.35
            assert imported.portrait_crop == PortraitCrop(x=0.35, y=0.45, zoom=2.2)
            assert imported.portrait_sprite_index == 1
            assert imported.emotion_tags == "立绘 1：smile\n立绘 2：angry\n"
            assert imported.sprite_groups == ["校服", "私服"]
            assert imported.default_sprite_group == "校服"
            assert imported.fallback_to_default_group is False
            assert imported.avatar_type == "l2d"
            assert imported.prompt_text == "Reference audio transcript."
            assert imported.prompt_lang == "ja"
            assert imported.speech_speed == 1.15
            assert imported.speech_volume == 0.85
            assert imported.pronunciation_map == {"Alice": "アリス"}
            assert imported.is_builtin is False
            assert imported.pinned is False
            assert imported.undeletable is False

            assert imported.relation_graph == RelationGraph.model_validate(
                {
                    "nodes": [{"key": expected_name}, {"key": "Bob"}],
                    "edges": [
                        {
                            "source": expected_name,
                            "target": "Bob",
                            "temperature": 7,
                            "content": "Best friend",
                        },
                        {
                            "source": "Bob",
                            "target": expected_name,
                            "temperature": 5,
                            "content": "Classmate",
                        },
                    ],
                }
            )

            # Static sprites + voice + mouth_sync
            assert len(imported.sprites) == 2
            s0, s1 = (Sprite.model_validate(item) for item in imported.sprites)
            for sprite, img_key, wav_key in (
                (s0, "smile.png", "smile.wav"),
                (s1, "angry.png", "angry.wav"),
            ):
                resolved_img = Path(sprite.path).resolve()
                assert resolved_img.is_relative_to((dst / "data" / "sprite" / expected_prefix).resolve())
                assert resolved_img.read_bytes() == expected_bytes[img_key]
                resolved_wav = Path(sprite.voice_path).resolve()
                assert resolved_wav.is_relative_to((dst / "data" / "speech" / expected_prefix).resolve())
                assert resolved_wav.read_bytes() == expected_bytes[wav_key]
            assert s0.voice_text == "Hello, nice to meet you!"
            assert s0.voice_type == "preset"
            assert s0.portrait_crop == PortraitCrop(x=0.25, y=0.35, zoom=2.5)
            assert s0.group == "校服"
            assert Path(s0.mouth_sync).resolve().is_relative_to(
                (dst / "data" / "sprite" / expected_prefix / "mouth-sync").resolve()
            )
            assert Path(s0.mouth_sync).read_bytes() == expected_bytes["mouth_manifest"]
            assert s1.voice_text == "Hmph!"
            assert s1.voice_type == "reference"
            assert s1.portrait_crop == PortraitCrop(x=0.6, y=0.4, zoom=1.8)
            assert s1.mouth_sync is None
            assert s1.group == "校服"

            # Sprite transitions
            assert len(imported.sprite_transitions) == 1
            edge = imported.sprite_transitions[0]
            assert edge.frame_count == 22
            assert edge.h3_resolution == "hd"
            assert edge.from_fingerprint == sprite_fingerprint(s0.path)
            assert edge.to_fingerprint == sprite_fingerprint(s1.path)
            assert Path(edge.from_path).resolve() == Path(s0.path).resolve()
            assert Path(edge.to_path).resolve() == Path(s1.path).resolve()
            clip_path = Path(edge.path).resolve()
            assert clip_path.is_relative_to(
                (dst / "data" / "sprite" / expected_prefix / "transitions").resolve()
            )
            assert clip_path.read_bytes() == expected_bytes["transition.webm"]
            assert len(list(valid_transitions(imported))) == 1

            # Avatar banks (active l2d + unbundled future metadata)
            assert set(imported.avatars) == {"l2d", "future"}
            l2d = imported.avatars["l2d"]
            l2d_model_dst = Path(l2d.model_path).resolve()
            assert l2d_model_dst.is_relative_to((dst / "data" / "sprite" / expected_prefix).resolve())
            assert l2d_model_dst.read_bytes() == expected_bytes["l2d_model"]
            assert (l2d_model_dst.parent / "alice.moc3").read_bytes() == expected_bytes["l2d_moc3"]
            assert (l2d_model_dst.parent / "tex.png").read_bytes() == expected_bytes["l2d_tex"]
            assert l2d.emotion_tags == "立绘 1：happy\n"
            assert len(l2d.sprites) == 1
            l2d_sp = Sprite.model_validate(l2d.sprites[0])
            assert Path(l2d_sp.path).resolve().is_relative_to(l2d_model_dst.parent.resolve())
            assert Path(l2d_sp.path).read_bytes() == expected_bytes["l2d_state"]
            assert Path(l2d_sp.voice_path).resolve().is_relative_to(
                (dst / "data" / "sprite" / expected_prefix).resolve()
            )
            assert Path(l2d_sp.voice_path).read_bytes() == expected_bytes["l2d_voice"]
            assert l2d_sp.voice_text == "L2D happy line"
            assert l2d_sp.voice_type == "preset"
            assert l2d_sp.portrait_crop == PortraitCrop(x=0.2, y=0.3, zoom=1.5)
            assert l2d_sp.group == "演出"
            assert imported.avatars["future"] == ModelSprites(
                model_path="models/alice/future.vrm",
                sprites=[],
                emotion_tags="1: future",
            )

            # Voice model & reference audio files
            for attr, byte_key in (
                ("gpt_model_path", "gpt_ckpt"),
                ("sovits_model_path", "sovits_pth"),
                ("refer_audio_path", "refer_wav"),
            ):
                model_file_path = Path(getattr(imported, attr)).resolve()
                assert model_file_path.is_relative_to((dst / "data" / "models" / expected_prefix).resolve())
                assert model_file_path.read_bytes() == expected_bytes[byte_key]

        _assert_character_preserved(char1, expected_name="Alice", expected_prefix="alice")

        # 2) Second import into the same destination (name & sprite_prefix conflict rename)
        second_imported = dst_uc.execute(
            parse_character_request(CharacterOperation.IMPORT, {"paths": [str(archive_path)]})
        )
        assert len(second_imported) == 1
        assert len(dst_cfg.config.characters) == 2
        char2 = dst_cfg.config.characters[1]
        assert char2.name != "Alice"
        assert char2.sprite_prefix != "alice"
        assert char1.id and char2.id and char1.id != char2.id
        _assert_character_preserved(
            char2,
            expected_name=char2.name,
            expected_prefix=char2.sprite_prefix,
        )


def test_forged_builtin_flags_in_character_package_are_stripped_on_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "forged.char"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "character.yaml",
            yaml.safe_dump(
                [
                    {
                        "name": "Forged",
                        "color": "#112233",
                        "sprite_prefix": "forged",
                        "is_builtin": True,
                        "pinned": True,
                        "undeletable": True,
                    }
                ],
                allow_unicode=True,
            ),
        )

    dst = tmp_path / "dst"
    dst.mkdir()
    with _isolated_file_util_workspace(dst, monkeypatch) as dst_paths:
        dst_cfg = _YamlBackedConfigManager(characters_yaml=dst_paths["characters_yaml"])
        dst_state = SimpleNamespace(
            config_manager=dst_cfg,
            character_manager=SimpleNamespace(),
            project_root_dir=str(dst),
            template_dir_path=str(dst / "data" / "character_templates"),
        )
        dst_uc = CharacterUseCase(dst_state, file_access_roots=(tmp_path,))
        dst_uc.execute(
            parse_character_request(CharacterOperation.IMPORT, {"paths": [str(archive)]})
        )
        assert len(dst_cfg.config.characters) == 1
        imported = dst_cfg.config.characters[0]
        assert imported.is_builtin is False
        assert imported.pinned is False
        assert imported.undeletable is False


# ── BackgroundUseCase End-to-End Round-Trip ────────────────────────────────


def test_background_use_case_export_import_preserves_every_field_and_conflict_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()

    with _isolated_file_util_workspace(src, monkeypatch) as src_paths:
        bg_dir = src / "data" / "backgrounds" / "classroom"
        bgm_dir = src / "data" / "bgm" / "classroom"
        bg_dir.mkdir(parents=True)
        bgm_dir.mkdir(parents=True)
        room_png = bg_dir / "room.png"
        sunset_png = bg_dir / "sunset.png"
        Image.new("RGB", (32, 24), "skyblue").save(room_png)
        Image.new("RGB", (32, 24), "orange").save(sunset_png)
        theme_mp3 = bgm_dir / "theme.mp3"
        theme_mp3.write_bytes(b"ID3-sunset-bgm")

        bg_payload = {
            "name": "Classroom",
            "sprite_prefix": "classroom",
            "sprites": [
                {"path": str(room_png), "portrait_crop": {"x": 0.4, "y": 0.5, "zoom": 1.75}},
                {"path": str(sunset_png)},
            ],
            "bg_tags": "背景 1：清晨教室\n背景 2：黄昏教室\n",
            "bgm_list": [str(theme_mp3)],
            "bgm_tags": "音乐 1：放学后的铃声\n",
        }
        assert set(bg_payload) == set(Background.model_fields) - RESERVED_BACKGROUND_FIELDS

        expected_room = room_png.read_bytes()
        expected_sunset = sunset_png.read_bytes()
        expected_bgm = theme_mp3.read_bytes()

        src_cfg = _YamlBackedConfigManager(
            background_yaml=src_paths["background_yaml"],
            backgrounds=[Background.model_validate(bg_payload)],
        )
        src_cfg.save_background_config()
        src_state = SimpleNamespace(
            config_manager=src_cfg,
            background_manager=SimpleNamespace(),
            project_root_dir=str(src),
        )
        src_uc = BackgroundUseCase(src_state, file_access_roots=(src,))
        export_result = src_uc.execute(
            parse_background_request(BackgroundOperation.EXPORT, {"name": "Classroom"})
        )
        assert isinstance(export_result, BackgroundExportResult)
        archive_path = (src / export_result.path).resolve()
        assert archive_path.is_file()

    with _isolated_file_util_workspace(dst, monkeypatch) as dst_paths:
        dst_cfg = _YamlBackedConfigManager(background_yaml=dst_paths["background_yaml"])
        dst_state = SimpleNamespace(
            config_manager=dst_cfg,
            background_manager=SimpleNamespace(),
            project_root_dir=str(dst),
        )
        dst_uc = BackgroundUseCase(dst_state, file_access_roots=(src, dst))

        def _assert_bg_preserved(
            imported: Background,
            *,
            expected_name: str,
            expected_prefix: str,
        ) -> None:
            assert imported.name == expected_name
            assert imported.sprite_prefix == expected_prefix
            assert imported.bg_tags == "背景 1：清晨教室\n背景 2：黄昏教室\n"
            assert imported.bgm_tags == "音乐 1：放学后的铃声\n"
            assert len(imported.sprites) == 2
            sp0, sp1 = (Sprite.model_validate(item) for item in imported.sprites)
            assert sp0.portrait_crop == PortraitCrop(x=0.4, y=0.5, zoom=1.75)
            assert Path(sp0.path).resolve().is_relative_to(
                (dst / "data" / "backgrounds" / expected_prefix).resolve()
            )
            assert Path(sp0.path).read_bytes() == expected_room
            assert Path(sp1.path).read_bytes() == expected_sunset
            assert len(imported.bgm_list) == 1
            bgm_dst = Path(imported.bgm_list[0]).resolve()
            assert bgm_dst.is_relative_to((dst / "data" / "bgm" / expected_prefix).resolve())
            assert bgm_dst.read_bytes() == expected_bgm

        dst_uc.execute(
            parse_background_request(BackgroundOperation.IMPORT, {"paths": [str(archive_path)]})
        )
        assert len(dst_cfg.config.background_list) == 1
        _assert_bg_preserved(
            dst_cfg.config.background_list[0],
            expected_name="Classroom",
            expected_prefix="classroom",
        )

        # Second import into same destination triggers conflict rename
        dst_uc.execute(
            parse_background_request(BackgroundOperation.IMPORT, {"paths": [str(archive_path)]})
        )
        assert len(dst_cfg.config.background_list) == 2
        bg2 = dst_cfg.config.background_list[1]
        assert bg2.name != "Classroom"
        assert bg2.sprite_prefix != "classroom"
        assert dst_cfg.config.background_list[0].id and bg2.id and dst_cfg.config.background_list[0].id != bg2.id
        _assert_bg_preserved(
            bg2,
            expected_name=bg2.name,
            expected_prefix=bg2.sprite_prefix,
        )


# ── EffectUseCase End-to-End Round-Trip ────────────────────────────────────


def test_effect_use_case_export_import_preserves_every_field_and_conflict_copy(
    tmp_path: Path,
) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src_fx_dir = src / "data" / "effects" / "Spark"
    src_fx_dir.mkdir(parents=True)
    dst.mkdir()

    fx_audio = src_fx_dir / "chime.wav"
    fx_image = src_fx_dir / "star.png"
    fx_image_audio = src_fx_dir / "twinkle.wav"
    fx_ambient = src_fx_dir / "rain.webm"
    fx_ambient_audio = src_fx_dir / "rain-loop.wav"
    fx_audio.write_bytes(b"RIFF-chime")
    Image.new("RGBA", (16, 16), (255, 220, 80, 255)).save(fx_image)
    fx_image_audio.write_bytes(b"RIFF-twinkle")
    fx_ambient.write_bytes(b"WEBM-rain")
    fx_ambient_audio.write_bytes(b"RIFF-rainloop")

    effect_payload = {
        "name": "Spark",
        "color": "#ff55aa",
        "prompt_text": "Play when a revelation occurs.",
        "audio_list": [str(fx_audio)],
        "audio_tags": "特效 1：清脆提示音\n",
        "image_list": [str(fx_image)],
        "image_tags": "图片 1：金色星芒\n",
        "image_audio_list": [str(fx_image_audio)],
        "ambient_list": [str(fx_ambient)],
        "ambient_tags": "环境 1：雨幕\n",
        "ambient_audio_list": [str(fx_ambient_audio)],
        "ambient_layers": ["front"],
    }
    assert set(effect_payload) == set(Effect.model_fields) - RESERVED_EFFECT_FIELDS

    expected_audio = fx_audio.read_bytes()
    expected_image = fx_image.read_bytes()
    expected_image_audio = fx_image_audio.read_bytes()
    expected_ambient = fx_ambient.read_bytes()
    expected_ambient_audio = fx_ambient_audio.read_bytes()

    src_cfg = _YamlBackedConfigManager(effects=[Effect.model_validate(effect_payload)])
    src_uc = EffectUseCase(src_cfg, project_root=src, local_file_access_roots=(src,))
    export_result = src_uc.execute(EffectRequest(EffectOperation.EXPORT, {"name": "Spark"}))
    assert isinstance(export_result, EffectExportResult)
    archive_path = (src / export_result.path).resolve()
    assert archive_path.is_file()

    dst_effect_yaml = dst / "data" / "config" / "effect.yaml"
    dst_effect_yaml.parent.mkdir(parents=True)
    dst_effect_yaml.write_text("[]\n", encoding="utf-8")
    dst_cfg = _YamlBackedConfigManager(effect_yaml=dst_effect_yaml)
    dst_uc = EffectUseCase(dst_cfg, project_root=dst, local_file_access_roots=(src, dst))

    def _assert_effect_preserved(imported: Effect, *, expected_name: str) -> None:
        assert imported.name == expected_name
        assert imported.color == "#ff55aa"
        assert imported.prompt_text == "Play when a revelation occurs."
        assert imported.audio_tags == "特效 1：清脆提示音\n"
        assert imported.image_tags == "图片 1：金色星芒\n"
        assert imported.ambient_tags == "环境 1：雨幕\n"
        assert imported.ambient_layers == ["front"]

        fx_dst_dir = (dst / "data" / "effects" / expected_name).resolve()
        assert len(imported.audio_list) == 1
        assert Path(imported.audio_list[0]).resolve().is_relative_to(fx_dst_dir)
        assert Path(imported.audio_list[0]).read_bytes() == expected_audio

        assert len(imported.image_list) == 1
        assert Path(imported.image_list[0]).resolve().is_relative_to(fx_dst_dir)
        assert Path(imported.image_list[0]).read_bytes() == expected_image

        assert len(imported.image_audio_list) == 1
        assert Path(imported.image_audio_list[0]).resolve().is_relative_to(fx_dst_dir)
        assert Path(imported.image_audio_list[0]).read_bytes() == expected_image_audio

        assert len(imported.ambient_list) == 1
        assert Path(imported.ambient_list[0]).resolve().is_relative_to(fx_dst_dir)
        assert Path(imported.ambient_list[0]).read_bytes() == expected_ambient

        assert len(imported.ambient_audio_list) == 1
        assert Path(imported.ambient_audio_list[0]).resolve().is_relative_to(fx_dst_dir)
        assert Path(imported.ambient_audio_list[0]).read_bytes() == expected_ambient_audio

    first = dst_uc.execute(EffectRequest(EffectOperation.IMPORT, {"paths": [str(archive_path)]}))
    assert len(first) == 1
    assert len(dst_cfg.config.effect_list) == 1
    _assert_effect_preserved(dst_cfg.config.effect_list[0], expected_name="Spark")

    # Second import into same destination triggers conflict rename
    second = dst_uc.execute(EffectRequest(EffectOperation.IMPORT, {"paths": [str(archive_path)]}))
    assert len(second) == 1
    assert len(dst_cfg.config.effect_list) == 2
    fx2 = dst_cfg.config.effect_list[1]
    assert fx2.name == "Spark_1"
    assert dst_cfg.config.effect_list[0].id and fx2.id and dst_cfg.config.effect_list[0].id != fx2.id
    _assert_effect_preserved(fx2, expected_name="Spark_1")
