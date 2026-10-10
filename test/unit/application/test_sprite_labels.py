from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.image_generation import labels
from application.media.auto_annotation import AnnotationCancelled, CHARACTER_PROMPT


def test_generated_images_are_labelled_in_order_and_partial_failures_are_preserved(
    tmp_path, monkeypatch
):
    files = [tmp_path / f"sprite-{index}.png" for index in range(3)]
    for index, file in enumerate(files):
        file.write_bytes(f"image-{index}".encode())
    describe = Mock(
        side_effect=[
            "smiling, waving",
            RuntimeError("Vision unavailable"),
            "calm, standing",
        ]
    )
    monkeypatch.setattr(labels, "configured_vision_available", lambda api: True)
    monkeypatch.setattr(
        labels, "configured_vision_manager", lambda: SimpleNamespace(describe=describe)
    )
    config = SimpleNamespace(config=SimpleNamespace(api_config=object()))
    tags, errors = labels.label_generated_sprites(
        config, [str(file) for file in files], output_dir=tmp_path
    )
    assert tags == ["smiling, waving", "", "calm, standing"]
    assert errors == [{"index": 1, "message": "Vision unavailable"}]
    assert [call.args for call in describe.call_args_list] == [
        (f"image-{index}".encode(), CHARACTER_PROMPT) for index in range(3)
    ]


def test_unconfigured_vision_keeps_generated_files_and_returns_actionable_errors(
    tmp_path, monkeypatch
):
    file = tmp_path / "sprite.png"
    file.write_bytes(b"generated")
    manager = Mock()
    monkeypatch.setattr(labels, "configured_vision_available", lambda api: False)
    monkeypatch.setattr(labels, "configured_vision_manager", manager)
    config = SimpleNamespace(config=SimpleNamespace(api_config=object()))
    tags, errors = labels.label_generated_sprites(
        config, [str(file)], output_dir=tmp_path
    )
    assert tags == [""]
    assert "视觉模型" in errors[0]["message"]
    assert file.read_bytes() == b"generated"
    manager.assert_not_called()


def test_annotation_does_not_read_files_outside_the_generated_output_directory(
    tmp_path, monkeypatch
):
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    describe = Mock()
    monkeypatch.setattr(labels, "configured_vision_available", lambda api: True)
    monkeypatch.setattr(
        labels, "configured_vision_manager", lambda: SimpleNamespace(describe=describe)
    )
    config = SimpleNamespace(config=SimpleNamespace(api_config=object()))
    tags, errors = labels.label_generated_sprites(
        config, [str(outside)], output_dir=output
    )
    assert tags == [""] and errors[0]["index"] == 0
    describe.assert_not_called()


def test_annotation_can_be_cancelled_before_inference(tmp_path, monkeypatch):
    file = tmp_path / "sprite.png"
    file.write_bytes(b"generated")
    describe = Mock()
    monkeypatch.setattr(labels, "configured_vision_available", lambda api: True)
    monkeypatch.setattr(
        labels, "configured_vision_manager", lambda: SimpleNamespace(describe=describe)
    )
    config = SimpleNamespace(config=SimpleNamespace(api_config=object()))
    with pytest.raises(AnnotationCancelled):
        labels.label_generated_sprites(
            config, [str(file)], output_dir=tmp_path, is_cancelled=lambda: True
        )
    describe.assert_not_called()
