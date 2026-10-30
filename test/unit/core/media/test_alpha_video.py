from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from core.media.alpha_video import remove_video_background, verify_alpha_video


def make_video(path, frames=5):
    import av

    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=12)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuv420p"
        for _ in range(frames):
            for packet in stream.encode(
                av.VideoFrame.from_image(Image.new("RGB", (32, 32), "white"))
            ):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_encodes_and_decodes_real_alpha_without_losing_frames(tmp_path):
    source, output = tmp_path / "source.mp4", tmp_path / "alpha.webm"
    make_video(source)
    seen = []

    def matte(image):
        result = Image.new("RGBA", image.size)
        ImageDraw.Draw(result).rectangle((8, 8, 24, 24), fill=(220, 50, 70, 200))
        return result

    result = remove_video_background(
        source, output, matte=matte, progress=lambda n, total: seen.append(n)
    )
    assert result["alphaVerified"] is True
    assert result["frameCount"] == verify_alpha_video(output) == 5
    assert result["duration"] == pytest.approx(5 / 12)
    assert seen == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("alpha", [0, 255])
def test_rejects_empty_or_opaque_matting_and_preserves_previous_output(tmp_path, alpha):
    source, output = tmp_path / "source.mp4", tmp_path / "alpha.webm"
    make_video(source)
    output.write_bytes(b"old usable result")
    with pytest.raises(ValueError, match="透明背景或人物"):
        remove_video_background(
            source,
            output,
            matte=lambda image: Image.new("RGBA", image.size, (100, 0, 0, alpha)),
        )
    assert output.read_bytes() == b"old usable result"
    assert not list(tmp_path.glob(".*.webm"))


def test_verifier_rejects_a_regular_opaque_video(tmp_path):
    source = tmp_path / "opaque.mp4"
    make_video(source)
    with pytest.raises(ValueError, match="Alpha"):
        verify_alpha_video(source)


def test_slows_exported_timeline_without_dropping_frames_or_alpha(tmp_path):
    import av

    source, output = tmp_path / "source.mp4", tmp_path / "slow.webm"
    make_video(source, frames=12)

    def matte(image):
        result = Image.new("RGBA", image.size)
        ImageDraw.Draw(result).rectangle((8, 8, 24, 24), fill=(220, 50, 70, 200))
        return result

    result = remove_video_background(source, output, matte=matte, playback_speed=0.75)
    assert result["frameCount"] == verify_alpha_video(output) == 12
    assert result["duration"] == pytest.approx(12 / 9)
    with av.open(str(output)) as container:
        assert float(container.streams.video[0].average_rate) == pytest.approx(9)
        assert container.duration / av.time_base == pytest.approx(12 / 9, abs=0.01)


def test_checks_duration_after_slowing_before_matting_and_keeps_old_output(tmp_path):
    source, output = tmp_path / "source.mp4", tmp_path / "slow.webm"
    make_video(source, frames=100)
    output.write_bytes(b"old usable result")

    def unexpected_matte(_):
        pytest.fail("Overlong slowed video must be rejected before matting")

    with pytest.raises(ValueError, match="放慢后的视频超过"):
        remove_video_background(
            source, output, matte=unexpected_matte, playback_speed=0.5
        )
    assert output.read_bytes() == b"old usable result"
