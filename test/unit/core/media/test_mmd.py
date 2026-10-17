import struct

import pytest

from core.media.avatar.mmd import MmdAdapter
from core.media.avatar.pmx import texture_references
from test.fixtures.pmx import pmx_bytes, pmx_sections


def _pmx(texture: str) -> bytes:
    return pmx_bytes(texture)


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


@pytest.mark.parametrize("version", [2.0, 2.1])
@pytest.mark.parametrize("index_size", [1, 2, 4])
@pytest.mark.parametrize("encoding", [0, 1])
@pytest.mark.parametrize("skin", range(5))
def test_complete_pmx_variable_sections(tmp_path, version, index_size, encoding, skin):
    model = tmp_path / "sample.pmx"
    model.write_bytes(pmx_bytes(version=version, index_size=index_size, encoding=encoding,
                                skin=skin, rich=True))
    assert MmdAdapter().inspect(model).files == (model,)


@pytest.mark.parametrize("section", ["textures", "materials", "bones", "morphs", "display", "rigid", "joints", "soft"])
@pytest.mark.parametrize("inside", [False, True])
def test_reject_pmx_truncated_at_or_inside_required_sections(tmp_path, section, inside):
    sections = pmx_sections(version=2.1, rich=True)
    data = b""
    for name, payload in sections.items():
        data += payload
        if name == section:
            break
    if inside:
        data = data[:-1]
    elif section == "soft":
        # The last required section must include at least its count.
        data = data[:-len(sections["soft"])]
    model = tmp_path / "sample.pmx"
    model.write_bytes(data)
    with pytest.raises(ValueError):
        MmdAdapter().inspect(model)


def test_reject_complete_zero_vertex_pmx(tmp_path):
    sections = pmx_sections(vertex_count=0)
    sections["faces"] = struct.pack("<i", 0)
    sections["materials"] = struct.pack("<i", 0)
    model = tmp_path / "sample.pmx"
    model.write_bytes(b"".join(sections.values()))
    with pytest.raises(ValueError, match="no vertices"):
        MmdAdapter().inspect(model)


@pytest.mark.parametrize("section", ["materials", "bones", "morphs", "display", "rigid", "joints", "soft"])
@pytest.mark.parametrize("count", [-1, 2_000_001])
def test_reject_invalid_required_section_counts(tmp_path, section, count):
    sections = pmx_sections(version=2.1, rich=True)
    sections[section] = struct.pack("<i", count) + sections[section][4:]
    model = tmp_path / "sample.pmx"
    model.write_bytes(b"".join(sections.values()))
    with pytest.raises(ValueError):
        MmdAdapter().inspect(model)


@pytest.mark.parametrize("mutation", ["nan", "inf", "empty faces", "bad face", "partial triangle", "no materials", "bad partition", "bad skin bone"])
def test_reject_unrenderable_geometry(tmp_path, mutation):
    sections = pmx_sections()
    if mutation in ("nan", "inf"):
        sections["vertices"] = sections["vertices"][:4] + struct.pack("<f", float(mutation)) + sections["vertices"][8:]
    elif mutation == "empty faces":
        sections["faces"] = struct.pack("<i", 0)
    elif mutation == "bad face":
        sections["faces"] = struct.pack("<iBBB", 3, 0, 1, 3)
    elif mutation == "partial triangle":
        sections["faces"] = struct.pack("<iBB", 2, 0, 1)
    elif mutation == "no materials":
        sections["materials"] = struct.pack("<i", 0)
    elif mutation == "bad partition":
        sections["materials"] = sections["materials"][:-4] + struct.pack("<i", 0)
    else:
        sections["vertices"] = sections["vertices"][:37] + b"\x01" + sections["vertices"][38:]
    model = tmp_path / "sample.pmx"
    model.write_bytes(b"".join(sections.values()))
    with pytest.raises(ValueError):
        MmdAdapter().inspect(model)


def test_pmx_21_requires_soft_body_count_even_when_empty(tmp_path):
    model = tmp_path / "sample.pmx"
    data = pmx_bytes(version=2.1)
    model.write_bytes(data[:-4])
    with pytest.raises(ValueError):
        MmdAdapter().inspect(model)
    model.write_bytes(data)
    assert MmdAdapter().inspect(model).files == (model,)


def test_every_truncated_prefix_of_complete_pmx_is_rejected():
    data = pmx_bytes(version=2.1, rich=True)
    for length in range(len(data)):
        with pytest.raises(ValueError):
            texture_references(data[:length])
    assert texture_references(data) == ("",)
