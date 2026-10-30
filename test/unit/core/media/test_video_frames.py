from pathlib import Path

import pytest
from PIL import Image

from core.media.video_frames import extract_video_frame


@pytest.fixture
def short_video(tmp_path):
    av = pytest.importorskip("av")
    video = tmp_path / "clip.mp4"
    with av.open(str(video), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
        for index in range(20):
            frame = av.VideoFrame.from_image(
                Image.new("RGB", (16, 16), "red" if index < 10 else "blue")
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return video


@pytest.mark.parametrize(
    "seconds,blue", [(None, True), (0, False), (0.2, False), (1.5, True), (2, True)]
)
def test_extracts_middle_or_selected_frame_without_changing_video(
    short_video, tmp_path, seconds, blue
):
    output = tmp_path / "frames" / "sprite.png"
    before = short_video.read_bytes()
    timestamp = extract_video_frame(short_video, output, seconds)
    with Image.open(output) as image:
        red, _, actual_blue = image.getpixel((8, 8))
        assert (actual_blue > red) is blue
        assert image.format == "PNG"
    assert short_video.read_bytes() == before
    assert 0 <= timestamp < 2
    assert not output.with_suffix(".frame.png").exists()


@pytest.mark.parametrize("seconds", [-1, True, "1", float("nan"), float("inf")])
def test_rejects_invalid_frame_time_before_reading_video(tmp_path, seconds):
    with pytest.raises(ValueError, match="秒数"):
        extract_video_frame(Path("not-read.mp4"), tmp_path / "sprite.png", seconds)


def test_rejects_time_beyond_clip(short_video, tmp_path):
    with pytest.raises(ValueError, match="超出了"):
        extract_video_frame(short_video, tmp_path / "sprite.png", 100)
