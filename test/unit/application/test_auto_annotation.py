from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from application.media.auto_annotation import (
    auto_label_background_images,
    auto_label_character_sprites,
)
from application.media.sprite_tags import normalize_sprite_tags
from core.media.asset_tags import normalize_generated_tags, tag_contents


class FakeConfigManager:
    def __init__(self, *, character=None, background=None):
        self.character = character
        self.background = background
        self.character_saves = 0
        self.background_saves = 0

    def get_character_by_name(self, name: str):
        return (
            self.character if self.character and self.character.name == name else None
        )

    def get_background_by_name(self, name: str):
        return (
            self.background
            if self.background and self.background.name == name
            else None
        )

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
    progress: list[tuple[int, int, str, str]] = []

    result = auto_label_character_sprites(
        config,
        "Nanami",
        project_root=tmp_path,
        infer=lambda _image, prompt: calls.append(prompt) or "标签：微笑，站立",
        on_progress=lambda completed, total, message, phase: progress.append(
            (completed, total, message, phase)
        ),
    )

    assert result["annotatedCount"] == 1
    assert result["skippedCount"] == 1
    assert tag_contents(result["tags"], 2) == ["手工标签", "微笑，站立"]
    assert config.character_saves == 1
    assert len(calls) == 1
    assert "2–3 个简短中文词语" in calls[0]
    assert "情绪" in calls[0] and "动作" in calls[0]
    assert progress[0][:2] == (0, 1)
    assert progress[0][3] == "loading-model"
    assert "1/1" in progress[0][2]
    assert progress[-1][:2] == (1, 1)


def test_background_auto_label_reports_invalid_asset_without_overwriting(
    tmp_path: Path,
):
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
            infer=lambda _image, _prompt: (_ for _ in ()).throw(
                RuntimeError("model failed")
            ),
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

    def infer(_image, _prompt):
        pytest.fail("out-of-project image must not be read")

    result = auto_label_character_sprites(
        config, "Nanami", project_root=tmp_path, infer=infer
    )

    assert result["failedCount"] == 1
    assert "项目目录" in result["failures"][0]["message"]
    assert config.character_saves == 0


def test_normalize_generated_tags_removes_wrappers():
    assert (
        normalize_generated_tags("```text\nTags: night; rainy\n```") == "night, rainy"
    )


def test_smart_label_uses_the_configured_vision_manager(tmp_path: Path, monkeypatch):
    character = SimpleNamespace(
        name="Nanami",
        sprites=[SimpleNamespace(path=_image(tmp_path, "one.png"))],
        emotion_tags="",
    )
    config = FakeConfigManager(character=character)
    calls: list[tuple[bytes, str]] = []
    configured = SimpleNamespace(
        describe=lambda image, prompt: calls.append((image, prompt)) or "平静，站立"
    )
    monkeypatch.setattr(
        "application.media.auto_annotation.configured_vision_manager",
        lambda **_kwargs: configured,
    )

    result = auto_label_character_sprites(config, "Nanami", project_root=tmp_path)

    assert result["annotatedCount"] == 1
    assert tag_contents(result["tags"], 1) == ["平静，站立"]
    assert calls and "2–3 个简短中文词语" in calls[0][1]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("标签：开心、微笑、挥手", "开心，微笑，挥手"),
        ("微笑,微笑,站立", "微笑，站立"),
        ("```text\n害羞，低头\n```", "害羞，低头"),
    ],
)
def test_sprite_tags_accept_only_short_chinese_emotion_action_words(raw, expected):
    assert normalize_sprite_tags(raw) == expected


def test_invalid_tag_format_is_retried_once_without_losing_manual_tags(tmp_path):
    character = SimpleNamespace(
        name="Nanami",
        sprites=[
            SimpleNamespace(path=_image(tmp_path, "one.png")),
            SimpleNamespace(path=_image(tmp_path, "two.png")),
        ],
        emotion_tags="立绘 1：手工标注\n立绘 2：\n",
    )
    config = FakeConfigManager(character=character)
    responses = iter(["smiling, waving", "开心，挥手"])
    prompts = []

    def infer(image, prompt):
        prompts.append(prompt)
        return next(responses)

    result = auto_label_character_sprites(
        config, "Nanami", project_root=tmp_path, infer=infer
    )
    assert result["annotatedCount"] == 1
    assert tag_contents(result["tags"], 2) == ["手工标注", "开心，挥手"]
    assert len(prompts) == 2 and "上次输出不符合格式" in prompts[1]


def test_noncompliant_tags_are_not_saved_and_current_api_config_is_used(
    tmp_path, monkeypatch
):
    character = SimpleNamespace(
        name="Nanami",
        sprites=[SimpleNamespace(path=_image(tmp_path, "one.png"))],
        emotion_tags="",
    )
    config = FakeConfigManager(character=character)
    current = SimpleNamespace(vision_provider="gemini")
    config.config = SimpleNamespace(api_config=current)
    seen = []

    def factory(*, api_config):
        seen.append(api_config)
        return SimpleNamespace(describe=lambda *_: "happy, standing")

    monkeypatch.setattr(
        "application.media.auto_annotation.configured_vision_manager", factory
    )
    result = auto_label_character_sprites(config, "Nanami", project_root=tmp_path)
    assert result["failedCount"] == 1 and result["annotatedCount"] == 0
    assert seen == [current]
    assert config.character_saves == 0 and character.emotion_tags == ""


def test_mp4_annotation_uses_a_middle_frame_and_cleans_it_up(tmp_path, monkeypatch):
    video = tmp_path / "animated.mp4"
    video.write_bytes(b"video")
    outputs = []

    def capture(source, output):
        assert source == video
        outputs.append(output)
        output.write_bytes(b"middle-frame")
        return 2.25

    monkeypatch.setattr("core.media.video_frames.extract_video_frame", capture)
    character = SimpleNamespace(
        name="Nanami", sprites=[SimpleNamespace(path="animated.mp4")], emotion_tags=""
    )

    def infer(image, prompt):
        assert image == b"middle-frame"
        return "开心，挥手"

    result = auto_label_character_sprites(
        FakeConfigManager(character=character),
        "Nanami",
        project_root=tmp_path,
        infer=infer,
    )
    assert result["annotatedCount"] == 1
    assert outputs and not outputs[0].exists()
