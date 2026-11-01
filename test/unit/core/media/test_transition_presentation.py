from PIL import Image, ImageDraw
import pytest

from core.media import transition_presentation as module


def sprite(path, size=(120, 200), padding=5, shade=96):
    image = Image.new("RGBA", size)
    ImageDraw.Draw(image).rectangle(
        (10, padding, size[0] - 11, size[1] - padding - 1),
        fill=(shade, shade, shade, 255),
    )
    image.save(path)
    return path


def test_reads_foreground_instead_of_transparent_padding_and_never_rewrites_assets(
    tmp_path,
):
    source = sprite(tmp_path / "from.png", shade=100)
    target = sprite(tmp_path / "to.png", size=(120, 192), padding=1, shade=104)
    clip = sprite(tmp_path / "bridge.png")
    contents = {p: p.read_bytes() for p in [source, target, clip]}
    data = module.transition_presentation(source, clip, target)
    assert data["first"]["luma"] == pytest.approx(96)
    assert data["to"]["luma"] == pytest.approx(104)
    assert data["first"]["bounds"][1] == pytest.approx(5 / 200)
    assert data["to"]["height"] == 192
    assert {p: p.read_bytes() for p in contents} == contents
    before = module._endpoints.cache_info().hits
    assert module.transition_presentation(source, clip, target) == data
    assert module._endpoints.cache_info().hits == before + 3
    sprite(clip, padding=10, shade=80)
    assert module.transition_presentation(source, clip, target)["first"][
        "luma"
    ] == pytest.approx(80)


def test_invalid_or_opaque_assets_have_no_calibration(tmp_path):
    source = sprite(tmp_path / "source.png")
    bad = tmp_path / "broken.webm"
    bad.write_bytes(b"not a video")
    assert module.transition_presentation(source, bad, source) is None
    opaque = tmp_path / "opaque.png"
    Image.new("RGB", (20, 30), "white").save(opaque)
    assert module.transition_presentation(source, opaque, source) is None


def test_decodes_both_video_endpoints_with_real_alpha(tmp_path):
    import av
    import numpy as np

    clip = tmp_path / "bridge.webm"
    with av.open(str(clip), "w") as out:
        stream = out.add_stream("libvpx-vp9", rate=24)
        stream.width = 120
        stream.height = 200
        stream.pix_fmt = "yuva420p"
        stream.options = {"lossless": "1", "auto-alt-ref": "0"}
        for shade in [70, 80, 90]:
            frame = Image.new("RGBA", (120, 200))
            ImageDraw.Draw(frame).rectangle(
                (10, 10, 109, 189), fill=(shade, shade, shade, 255)
            )
            for packet in stream.encode(
                av.VideoFrame.from_ndarray(np.asarray(frame), format="rgba")
            ):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    source = sprite(tmp_path / "source.png")
    data = module.transition_presentation(source, clip, source)
    assert data["first"]["luma"] == pytest.approx(70, abs=2)
    assert data["last"]["luma"] == pytest.approx(90, abs=2)
