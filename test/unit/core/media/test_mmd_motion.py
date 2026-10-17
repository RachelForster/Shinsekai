import struct
from pathlib import Path

import pytest

from core.media.avatar.mmd import MmdAdapter
from core.media.avatar.mmd_motion import inspect_motion
from test.fixtures.mmd_motion import vpd_bytes, vmd_bytes, vmd_exporter_bytes
from test.fixtures.pmx import pmx_bytes


def test_large_vpd_advances_match_offsets_without_copying_suffixes(tmp_path, monkeypatch):
    from core.media.avatar import mmd_motion

    class NoSuffixCopy(str):
        def __getitem__(self, key):
            if isinstance(key, slice) and key.start and key.stop is None:
                pytest.fail("VPD parser copied the unconsumed suffix")
            return super().__getitem__(key)

    original_sub = mmd_motion.re.sub
    monkeypatch.setattr(mmd_motion.re, "sub", lambda *args: NoSuffixCopy(original_sub(*args)))
    count = 20_000
    text = f"Vocaloid Pose Data file\nsample.osm;\n{count};\n"
    text += "".join(f"Bone{i}{{bone{i}\n0,0,0;\n0,0,0,1;\n}}\n" for i in range(count))
    source = tmp_path / "large.vpd"
    source.write_text(text + " \n\t", encoding="utf-8")
    assert len(inspect_motion(source).bones) == count


@pytest.mark.parametrize("failure", ["directory", "non-directory-parent", "missing", "stat-denied", "read-denied"])
def test_preset_filesystem_errors_are_validation_failures(tmp_path, monkeypatch, failure):
    source = tmp_path / "pose.vpd"
    source.write_bytes(vpd_bytes())
    if failure == "directory":
        source.unlink()
        source.mkdir()
    elif failure == "non-directory-parent":
        source = source / "pose.vmd"
    elif failure == "missing":
        source.unlink()
    else:
        method = "stat" if failure == "stat-denied" else "read_bytes"
        original = getattr(Path, method)
        def denied(path, *args, **kwargs):
            if path == source:
                raise PermissionError("unreadable preset")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, method, denied)
    with pytest.raises(ValueError):
        inspect_motion(source)
    model = tmp_path / "model.pmx"
    model.write_bytes(pmx_bytes())
    with pytest.raises(ValueError):
        MmdAdapter().parse_state(model, {
            "morphs": {}, "mouthMorph": "", "blinkMorph": "",
            "motion": source.relative_to(tmp_path).as_posix(),
        })


@pytest.mark.parametrize("extension,data", [
    ("vpd", vpd_bytes("頭")), ("VPD", vpd_bytes("頭", encoding="cp932")),
    ("vmd", vmd_bytes("頭")), ("VMD", vmd_bytes("頭", optional=False)),
])
def test_motion_targets_and_encodings(tmp_path, extension, data):
    file = tmp_path / f"motion.{extension}"
    file.write_bytes(data)
    assert inspect_motion(file).bones == {"頭"}


@pytest.mark.parametrize("metadata", ["model-name", "interpolation-padding"])
def test_vmd_ignores_metadata_not_used_by_the_runtime(tmp_path, metadata):
    source = tmp_path / "exported.vmd"
    source.write_bytes(vmd_exporter_bytes("頭", metadata=metadata))
    assert inspect_motion(source).bones == {"頭"}


@pytest.mark.parametrize("frame", [0, 1])
@pytest.mark.parametrize("index", [*range(16), *range(16, 64, 4)])
def test_vmd_rejects_invalid_active_interpolation_parameters(tmp_path, frame, index):
    data = bytearray(vmd_bytes())
    data[54 + frame * 111 + 47 + index] = 0xff
    source = tmp_path / "bad.vmd"
    source.write_bytes(data)
    with pytest.raises(ValueError, match="interpolation"):
        inspect_motion(source)


@pytest.mark.parametrize("payload", [
    b"", vpd_bytes().replace(b"1;", b"2;"), vpd_bytes()[:-3],
    vpd_bytes(angle="nan,0,0,1"), vpd_bytes(angle="0,0,0,0"),
    vpd_bytes().replace(b"Bone0", b"Other0"), vpd_bytes() + b"junk",
    vpd_bytes().replace(b"0,0,0;", b"inf,0,0;"),
])
def test_reject_invalid_vpd(tmp_path, payload):
    file = tmp_path / "bad.vpd"
    file.write_bytes(payload)
    with pytest.raises(ValueError):
        inspect_motion(file)


def test_vmd_every_truncation_is_rejected_except_optional_section_boundaries(tmp_path):
    data = vmd_bytes(morph="smile")
    file = tmp_path / "bad.vmd"
    # Header + bones + required morphs, then four optional section counts.
    optional_start = 50 + 4 + 2 * 111 + 4 + 23
    for length in range(len(data)):
        file.write_bytes(data[:length])
        if length in range(optional_start, len(data), 4):
            assert inspect_motion(file).morphs == {"smile"}
        else:
            with pytest.raises(ValueError):
                inspect_motion(file)


@pytest.mark.parametrize("offset,replacement", [
    (0, b"BAD"), (50, struct.pack("<I", 0xffffffff)),
    (54 + 15 + 4, struct.pack("<f", float("nan"))),
    (54 + 15 + 4 + 28, b"\xff"),
])
def test_reject_corrupt_vmd(tmp_path, offset, replacement):
    data = bytearray(vmd_bytes())
    data[offset:offset + len(replacement)] = replacement
    file = tmp_path / "bad.vmd"
    file.write_bytes(data)
    with pytest.raises(ValueError):
        inspect_motion(file)


def test_motion_state_dependencies_and_model_compatibility(tmp_path):
    model = tmp_path / "model.pmx"
    model.write_bytes(pmx_bytes())
    motion = tmp_path / "pose.vpd"
    motion.write_bytes(vpd_bytes())
    adapter = MmdAdapter()
    base = {"morphs": {}, "mouthMorph": "", "blinkMorph": ""}
    value = adapter.import_state(model, motion, "pose.vpd", base)
    parsed = adapter.parse_state(model, value)
    assert parsed["motion"] == "pose.vpd"
    assert adapter.state_files(model, parsed) == (motion,)
    for path in ("../pose.vpd", "/pose.vpd", "C:/pose.vpd", "a\\pose.vpd", "%2e%2e/pose.vpd", "pose.vpd?x", "pose.vpd\0"):
        with pytest.raises((ValueError, PermissionError)):
            adapter.parse_state(model, {**base, "motion": path})
    motion.write_bytes(vpd_bytes("other-model-bone"))
    with pytest.raises(ValueError, match="matching"):
        adapter.parse_state(model, value)
