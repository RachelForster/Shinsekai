import pytest

from application.media.auto_annotation import _annotation_image_bytes


@pytest.mark.parametrize("suffix", [".mp4", ".webm"])
def test_video_annotation_uses_a_temporary_image_frame_and_removes_it(
    tmp_path, monkeypatch, suffix
):
    from core.media import video_frames

    source = tmp_path / f"sprite{suffix}"
    source.write_bytes(b"video source")
    outputs = []

    def extract(path, output):
        assert path == source
        assert output.suffix == ".png"
        outputs.append(output)
        output.write_bytes(b"image frame bytes")

    monkeypatch.setattr(video_frames, "extract_video_frame", extract)
    assert _annotation_image_bytes(source, tmp_path) == b"image frame bytes"
    assert len(outputs) == 1 and not outputs[0].exists()


def test_static_annotation_reads_the_original_image_bytes(tmp_path):
    source = tmp_path / "sprite.png"
    source.write_bytes(b"original image")
    assert _annotation_image_bytes(source, tmp_path) == b"original image"
