import json
import struct
from pathlib import Path

import pytest

from core.media.avatar.vrm import VrmAssetAdapter, read_glb


def glb(path: Path, extension: str = "VRMC_vrm", **extra) -> Path:
    value = {"asset": {"version": "2.0"}, "extensions": {extension: {}}, **extra}
    payload = json.dumps(value).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    path.write_bytes(
        struct.pack("<4sIIII", b"glTF", 2, 20 + len(payload), len(payload), 0x4E4F534A)
        + payload
    )
    return path


def test_inspect_accepts_vrm_0_and_1_and_rejects_external_resources(tmp_path):
    model = glb(tmp_path / "model.vrm", "VRM")
    assert VrmAssetAdapter().inspect(model).files == (model,)
    glb(model)
    assert VrmAssetAdapter().inspect(model).entry == model
    glb(model, images=[{"uri": "https://example.test/image.png"}])
    with pytest.raises(ValueError, match="self-contained"):
        VrmAssetAdapter().inspect(model)
    glb(model, buffers=[{"uri": "../mesh.bin"}])
    with pytest.raises(ValueError, match="self-contained"):
        VrmAssetAdapter().inspect(model)


@pytest.mark.parametrize("body", [b"", b"glTF", b"bad!", b"glTF" + b"\x00" * 16])
def test_rejects_truncated_or_invalid_glb(tmp_path, body):
    model = tmp_path / "bad.vrm"
    model.write_bytes(body)
    with pytest.raises(ValueError):
        read_glb(model)


def test_rejects_invalid_resource_shape(tmp_path):
    model = glb(tmp_path / "model.vrm", images=[False])
    with pytest.raises(ValueError, match="resource"):
        VrmAssetAdapter().inspect(model)


def test_shared_vrm_state_fixtures_match_python_boundary(tmp_path):
    fixtures = Path(__file__).resolve().parents[4] / "frontend/src/test/fixtures/vrm-states.json"
    for case in json.loads(fixtures.read_text(encoding="utf-8")):
        if case["valid"]:
            assert VrmAssetAdapter().parse_state(tmp_path / "model.vrm", case["state"])
        else:
            with pytest.raises(ValueError):
                VrmAssetAdapter().parse_state(tmp_path / "model.vrm", case["state"])


def test_vrma_import_and_state_dependency(tmp_path):
    adapter = VrmAssetAdapter()
    model = glb(tmp_path / "model.vrm")
    folder = tmp_path / "states"
    folder.mkdir()
    motion = glb(folder / "motion.vrma", "VRMC_vrm_animation")
    base = {"expressions": {"happy": 0.5}, "bones": {}, "motion": ""}
    state = adapter.import_state(model, motion, "states/motion.vrma", base)
    assert state == {**base, "motion": "states/motion.vrma"}
    assert adapter.parse_state(model, state) == state
    assert adapter.state_files(model, state) == (motion,)
    with pytest.raises(ValueError):
        adapter.import_state(model, model, "states/model.vrma", base)


@pytest.mark.parametrize("motion", [
    "../outside.vrma", "C:/outside.vrma", "states\\motion.vrma",
    "states/%2e%2e/motion.vrma", "states//motion.vrma",
])
def test_rejects_unsafe_vrma_reference(tmp_path, motion):
    model = glb(tmp_path / "model.vrm")
    state = {"expressions": {}, "bones": {}, "motion": motion}
    with pytest.raises((ValueError, PermissionError)):
        VrmAssetAdapter().parse_state(model, state)


def test_motion_timing_is_saved_but_is_not_inherited_by_an_imported_motion(tmp_path):
    adapter = VrmAssetAdapter()
    model = glb(tmp_path / "model.vrm")
    motion = glb(tmp_path / "motion.vrma", "VRMC_vrm_animation",
                 animations=[{"samplers": [{"input": 0}]}], accessors=[{"max": [6]}])
    timing = {"entryStart": 0.6, "bodyStart": 2, "bodyEnd": 4, "exitEnd": 5}
    value = {"expressions": {}, "bones": {}, "motion": motion.name, "motionTiming": timing}
    assert adapter.parse_state(model, value)["motionTiming"] == timing
    assert "motionTiming" not in adapter.import_state(model, motion, "another.vrma", value)


@pytest.mark.parametrize("timing", [
    None, [], {}, {"entryStart": 1},
    {"entryStart": -1, "bodyStart": 2, "bodyEnd": 3, "exitEnd": 4},
    {"entryStart": 2, "bodyStart": 1, "bodyEnd": 3, "exitEnd": 4},
    {"entryStart": 0, "bodyStart": 1, "bodyEnd": float("inf"), "exitEnd": float("inf")},
    {"entryStart": False, "bodyStart": 1, "bodyEnd": 2, "exitEnd": 3},
    {"entryStart": 0, "bodyStart": 1, "bodyEnd": 2, "exitEnd": 7},
])
def test_invalid_motion_timing_is_rejected(tmp_path, timing):
    model = glb(tmp_path / "model.vrm")
    motion = glb(tmp_path / "motion.vrma", "VRMC_vrm_animation",
                 animations=[{"samplers": [{"input": 0}]}], accessors=[{"max": [6]}])
    with pytest.raises(ValueError):
        VrmAssetAdapter().parse_state(model, {"expressions": {}, "bones": {}, "motion": motion.name, "motionTiming": timing})
