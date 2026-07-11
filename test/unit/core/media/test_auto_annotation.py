from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.media.asset_tags import normalize_generated_tags, tag_contents
from core.media.auto_annotation import auto_label_background_images, auto_label_character_sprites


class FakeConfigManager:
    def __init__(self, *, character=None, background=None):
        self.character = character
        self.background = background
        self.character_saves = 0
        self.background_saves = 0

    def get_character_by_name(self, name: str):
        return self.character if self.character and self.character.name == name else None

    def get_background_by_name(self, name: str):
        return self.background if self.background and self.background.name == name else None

    def save_characters_config(self):
        self.character_saves += 1

    def save_background_config(self):
        self.background_saves += 1


def _image(root: Path, name: str) -> str:
    path = root / name
    path.write_bytes(b"image")
    return path.relative_to(root).as_posix()


def test_character_auto_label_only_fills_blank_tags(tmp_path: Path):
    character = SimpleNamespace(
        name="Nanami",
        sprites=[
            SimpleNamespace(path=_image(tmp_path, "one.png")),
            SimpleNamespace(path=_image(tmp_path, "two.webp")),
        ],
        emotion_tags="立绘 1：手工标签\n立绘 2：\n",
    )
    config = FakeConfigManager(character=character)
    calls: list[str] = []

    result = auto_label_character_sprites(
        config,
        "Nanami",
        project_root=tmp_path,
        infer=lambda _image, prompt: calls.append(prompt) or "Tags: smiling, front-facing pose",
    )

    assert result["annotatedCount"] == 1
    assert result["skippedCount"] == 1
    assert tag_contents(result["tags"], 2) == ["手工标签", "smiling, front-facing pose"]
    assert config.character_saves == 1
    assert len(calls) == 1
    assert "concise English tags" in calls[0]
    assert "comma-separated" in calls[0]


def test_background_auto_label_reports_invalid_asset_without_overwriting(tmp_path: Path):
    background = SimpleNamespace(
        name="Room",
        sprites=[SimpleNamespace(path="missing.png")],
        bg_tags="",
    )
    config = FakeConfigManager(background=background)

    result = auto_label_background_images(
        config,
        "Room",
        project_root=tmp_path,
        infer=lambda _image, _prompt: "unused",
    )

    assert result["annotatedCount"] == 0
    assert result["failedCount"] == 1
    assert config.background_saves == 0
    assert background.bg_tags == ""


def test_inference_runtime_errors_abort_without_saving(tmp_path: Path):
    character = SimpleNamespace(
        name="Nanami",
        sprites=[SimpleNamespace(path=_image(tmp_path, "one.jpg"))],
        emotion_tags="",
    )
    config = FakeConfigManager(character=character)

    with pytest.raises(RuntimeError, match="model failed"):
        auto_label_character_sprites(
            config,
            "Nanami",
            project_root=tmp_path,
            infer=lambda _image, _prompt: (_ for _ in ()).throw(RuntimeError("model failed")),
        )

    assert config.character_saves == 0


def test_asset_paths_cannot_escape_the_project_root(tmp_path: Path):
    outside = tmp_path.parent / f"outside-{tmp_path.name}.png"
    outside.write_bytes(b"image")
    character = SimpleNamespace(
        name="Nanami",
        sprites=[SimpleNamespace(path=str(outside))],
        emotion_tags="",
    )
    config = FakeConfigManager(character=character)
    infer = lambda _image, _prompt: pytest.fail("out-of-project image must not be read")

    result = auto_label_character_sprites(config, "Nanami", project_root=tmp_path, infer=infer)

    assert result["failedCount"] == 1
    assert "项目目录" in result["failures"][0]["message"]
    assert config.character_saves == 0


def test_normalize_generated_tags_removes_wrappers():
    assert normalize_generated_tags("```text\nTags: night; rainy\n```") == "night, rainy"
