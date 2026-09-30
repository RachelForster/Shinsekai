import struct

import pytest

from core.media.avatar.mmd import MmdAdapter


def _pmx(texture: str) -> bytes:
    def text(value: str) -> bytes:
        encoded = value.encode("utf-8")
        return struct.pack("<i", len(encoded)) + encoded

    return (
        b"PMX "
        + struct.pack("<fB", 2.0, 8)
        + bytes((1, 0, 1, 1, 1, 1, 1, 1))
        + text("") * 4
        + struct.pack("<iii", 0, 0, 1)
        + text(texture)
    )


def test_inspect_pmx_package_with_windows_texture_separator(tmp_path):
    texture = tmp_path / "tex" / "eye.png"
    texture.parent.mkdir()
    texture.write_bytes(b"png")
    model = tmp_path / "sample.pmx"
    model.write_bytes(_pmx(r"tex\eye.png"))
    result = MmdAdapter().inspect(model)
    assert result.entry == model
    assert result.files == (model, texture)


@pytest.mark.parametrize("texture", [r"..\secret.png", "C:/secret.png", "/etc/passwd", "tex/%2e%2e/x.png"])
def test_reject_escaped_pmx_texture(tmp_path, texture):
    model = tmp_path / "sample.pmx"
    model.write_bytes(_pmx(texture))
    with pytest.raises((ValueError, PermissionError)):
        MmdAdapter().inspect(model)


def test_missing_texture_fails_import(tmp_path):
    model = tmp_path / "sample.pmx"
    model.write_bytes(_pmx("tex/missing.png"))
    with pytest.raises(FileNotFoundError):
        MmdAdapter().inspect(model)


def test_mmd_state_round_trip_and_invalid_weights(tmp_path):
    model = tmp_path / "sample.pmx"
    model.write_bytes(_pmx(""))
    state = {"morphs": {"笑顔": 0.7}, "mouthMorph": "あ", "blinkMorph": "まばたき"}
    camera = {"yaw": 0, "pitch": 0, "zoom": 1, "panX": 0, "panY": 0}
    assert MmdAdapter().parse_state(model, state) == {**state, "camera": camera}
    custom = {**state, "camera": {"yaw": 35, "pitch": -10, "zoom": 2, "panX": 0.1, "panY": -0.2}}
    assert MmdAdapter().parse_state(model, custom) == custom
    for weight in (float("nan"), float("inf"), -0.1, 1.1, True):
        with pytest.raises(ValueError):
            MmdAdapter().parse_state(model, {**state, "morphs": {"笑顔": weight}})


@pytest.mark.parametrize("camera", [
    None, {}, {"yaw": 0, "pitch": 0, "zoom": 1, "panX": 0, "panY": 0, "extra": 1},
    *({"yaw": 0, "pitch": 0, "zoom": 1, "panX": 0, "panY": 0, key: value}
      for key, value in [("yaw", 181), ("pitch", -81), ("zoom", 0), ("panX", 2), ("panY", float("nan")), ("zoom", True)]),
])
def test_reject_invalid_camera(tmp_path, camera):
    model = tmp_path / "sample.pmx"
    model.write_bytes(_pmx(""))
    with pytest.raises(ValueError):
        MmdAdapter().parse_state(model, {"morphs": {}, "mouthMorph": "", "blinkMorph": "", "camera": camera})


def test_truncated_pmx_fails_closed(tmp_path):
    model = tmp_path / "sample.pmx"
    model.write_bytes(_pmx("tex/eye.png")[:-3])
    with pytest.raises(ValueError):
        MmdAdapter().inspect(model)
