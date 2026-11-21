"""Tests for split character/background ops, SQLite catalog routing, and id-anchored patch saves."""

from __future__ import annotations

from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import wave

import pytest

from application.backgrounds.management import (
    BackgroundOperation,
    BackgroundRequest,
    BackgroundUseCase,
)
from application.character_relation.manage_relations import build_relation_use_case
from application.characters.management import (
    CharacterOperation,
    CharacterRequest,
    CharacterUseCase,
)
from application.runtime.stores import build_app_stores


_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
    b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_wav(path: Path, *, duration_seconds: float = 4.0, sample_rate: int = 16000) -> Path:
    frame_count = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack("<h", 0) * frame_count)
    return path


def _make_state(tmp_path: Path, stores):
    return SimpleNamespace(
        project_root_dir=str(tmp_path),
        template_dir_path=str(tmp_path / "templates"),
        stores=stores,
        character_manager=None,
        background_manager=None,
        config_manager=SimpleNamespace(
            config=SimpleNamespace(characters=[], background_list=[]),
            refresh_characters=lambda: None,
            refresh_backgrounds=lambda: None,
            reload=lambda: None,
            get_character_by_name=stores.characters.get_by_name,
            get_background_by_name=stores.backgrounds.get_by_name,
        ),
    )


def test_legacy_manager_facades_stay_compact() -> None:
    root = Path(__file__).resolve().parents[4]
    char_lines = (root / "config" / "character_manager.py").read_text(encoding="utf-8").splitlines()
    bg_lines = (root / "config" / "background_manager.py").read_text(encoding="utf-8").splitlines()
    assert len(char_lines) < 240
    assert len(bg_lines) < 240


def test_character_use_case_patch_save_and_direct_catalog_ops(tmp_path: Path) -> None:
    stores = build_app_stores(tmp_path, bind_globals=False)
    try:
        state = _make_state(tmp_path, stores)
        use_case = CharacterUseCase(state, file_access_roots=[tmp_path])
        relations = build_relation_use_case(state.config_manager, characters=stores.characters)

        sprite_file = tmp_path / "smile.png"
        sprite_file.write_bytes(_PNG_1X1)
        voice_file = _write_wav(tmp_path / "line.wav", duration_seconds=4.0)

        created = use_case.execute(
            CharacterRequest(
                CharacterOperation.SAVE,
                {
                    "character": {
                        "name": "Alice",
                        "color": "#123456",
                        "sprite_prefix": "alice",
                        "character_brief": "Initial brief",
                        "portrait_sprite_index": 0,
                        "pronunciation_map": {"Alice": "Arisu"},
                    }
                },
            )
        )
        char_id = created["id"]
        assert char_id

        with_sprite = use_case.execute(
            CharacterRequest(
                CharacterOperation.UPLOAD_SPRITES,
                {"name": "Alice", "paths": [str(sprite_file)]},
            )
        )
        assert len(with_sprite["sprites"]) == 1

        use_case.execute(
            CharacterRequest(
                CharacterOperation.SAVE_EMOTION_TAGS,
                {"name": "Alice", "emotionTags": "立绘 1：smile"},
            )
        )
        use_case.execute(
            CharacterRequest(
                CharacterOperation.SAVE_SPRITE_SCALE,
                {"name": "Alice", "scale": 1.35},
            )
        )
        use_case.execute(
            CharacterRequest(
                CharacterOperation.UPLOAD_SPRITE_VOICE,
                {
                    "name": "Alice",
                    "spriteIndex": 0,
                    "voicePath": str(voice_file),
                    "voiceText": "Hello there",
                    "voiceType": "reference",
                },
            )
        )
        use_case.execute(
            CharacterRequest(
                CharacterOperation.SAVE_SPRITE_GROUPS,
                {
                    "name": "Alice",
                    "spriteGroups": ["casual"],
                    "defaultSpriteGroup": "casual",
                    "fallbackToDefaultGroup": True,
                    "assignments": {"0": "casual"},
                },
            )
        )
        relations.apply_relation_changes("Alice", [{"op": "add_node", "node": {"key": "Bob"}}])

        renamed = use_case.execute(
            CharacterRequest(
                CharacterOperation.SAVE,
                {
                    "id": char_id,
                    "character": {
                        "name": "Alicia",
                        "sprite_prefix": "alicia",
                    },
                },
            )
        )
        assert renamed["id"] == char_id
        assert renamed["name"] == "Alicia"
        assert renamed["sprite_prefix"] == "alicia"
        assert renamed["color"] == "#123456"
        assert renamed["character_brief"] == "Initial brief"
        assert renamed["pronunciation_map"] == {"Alice": "Arisu"}
        assert renamed["sprite_scale"] == pytest.approx(1.35)
        assert renamed["emotion_tags"].strip() == "立绘 1：smile"
        assert len(renamed["sprites"]) == 1
        assert renamed["sprites"][0]["group"] == "casual"
        assert renamed["sprites"][0]["voice_text"] == "Hello there"
        assert stores.characters.get_by_name("Alice") is None
        assert stores.characters.get(char_id).name == "Alicia"

        migrated_graph = relations.get_relation_graph("Alicia")
        assert migrated_graph["owner"] == "Alicia"
        assert any(node["key"] == "Alicia" for node in migrated_graph["nodes"])
        assert any(node["key"] == "Bob" for node in migrated_graph["nodes"])

        remaining = use_case.execute(
            CharacterRequest(CharacterOperation.DELETE, {"name": "Alicia"})
        )
        assert stores.characters.get(char_id) is None
        assert "Alicia" not in remaining["names"]
    finally:
        stores.close()


def test_background_use_case_patch_save_and_bgm_ops_without_pandas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pandas", None)
    stores = build_app_stores(tmp_path, bind_globals=False)
    try:
        state = _make_state(tmp_path, stores)
        use_case = BackgroundUseCase(state, file_access_roots=[tmp_path])

        bgm_file = _write_wav(tmp_path / "theme.wav", duration_seconds=2.0)

        created = use_case.execute(
            BackgroundRequest(
                BackgroundOperation.SAVE,
                {
                    "background": {
                        "name": "Campus",
                        "sprite_prefix": "campus",
                    }
                },
            )
        )
        bg_id = created["id"]
        assert bg_id

        use_case.execute(
            BackgroundRequest(
                BackgroundOperation.UPLOAD_BGM,
                {"name": "Campus", "paths": [str(bgm_file)]},
            )
        )
        use_case.execute(
            BackgroundRequest(
                BackgroundOperation.SAVE_IMAGE_TAGS,
                {"name": "Campus", "bgTags": "立绘 1：morning"},
            )
        )
        use_case.execute(
            BackgroundRequest(
                BackgroundOperation.SAVE_BGM_TAGS,
                {"name": "Campus", "bgmTags": "音乐 1：theme"},
            )
        )

        renamed = use_case.execute(
            BackgroundRequest(
                BackgroundOperation.SAVE,
                {
                    "id": bg_id,
                    "background": {
                        "name": "Rooftop",
                        "sprite_prefix": "roof",
                    },
                },
            )
        )
        assert renamed["id"] == bg_id
        assert renamed["name"] == "Rooftop"
        assert renamed["sprite_prefix"] == "roof"
        assert renamed["bg_tags"] == "立绘 1：morning"
        assert renamed["bgm_tags"] == "音乐 1：theme"
        assert len(renamed["bgm_list"]) == 1
        assert stores.backgrounds.get_by_name("Campus") is None
        assert stores.backgrounds.get(bg_id).name == "Rooftop"

        remaining = use_case.execute(
            BackgroundRequest(BackgroundOperation.DELETE, {"name": "Rooftop"})
        )
        assert stores.backgrounds.get(bg_id) is None
        assert "Rooftop" not in remaining["names"]
    finally:
        stores.close()
