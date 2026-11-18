"""VRM model and VRMA state validation; no renderer or character state here."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from sdk.adapters import ModelAssetAdapter, ModelCapabilities, ModelFiles
from sdk.path_utils import is_portable_relative_path, safe_child_path

_MAX_JSON_BYTES = 32 * 1024 * 1024


def read_glb(path: Path) -> dict:
    """Read only the bounded JSON chunk and reject external package references."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError("Invalid GLB header")
        magic, version, declared_size = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or declared_size != size:
            raise ValueError("Expected a GLB 2.0 file")
        chunk = stream.read(8)
        if len(chunk) != 8:
            raise ValueError("Missing GLB JSON")
        length, kind = struct.unpack("<II", chunk)
        if kind != 0x4E4F534A or length > min(size - 20, _MAX_JSON_BYTES):
            raise ValueError("Invalid GLB JSON chunk")
        payload = stream.read(length)
        if len(payload) != length:
            raise ValueError("Truncated GLB JSON")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid GLB JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("extensions"), dict):
        raise ValueError("Invalid glTF document")
    for key in ("buffers", "images"):
        entries = value.get(key, [])
        if not isinstance(entries, list):
            raise ValueError("Invalid glTF resources")
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("Invalid glTF resource")
            uri = item.get("uri", "")
            if not isinstance(uri, str) or (uri and not uri.startswith("data:")):
                raise ValueError("Export a self-contained VRM/VRMA")
    return value


def package_file(model: Path, relative: str) -> Path:
    if (
        not is_portable_relative_path(relative)
        or any(char in relative for char in "\\:?#%\x00")
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise ValueError("Dependency must stay inside the model package")
    path = safe_child_path(model.resolve(strict=True).parent, relative)
    if not path.is_file():
        raise ValueError("Missing model dependency")
    return path


class VrmAssetAdapter(ModelAssetAdapter):
    format_id = "vrm"
    capabilities = ModelCapabilities(mouth=True, blink=True, motion=True, sampling="single")

    def inspect(self, source: Path) -> ModelFiles:
        source = source.resolve(strict=True)
        if source.suffix.lower() != ".vrm":
            raise ValueError("Choose a .vrm model")
        if not {"VRM", "VRMC_vrm"}.intersection(read_glb(source)["extensions"]):
            raise ValueError("The model has no VRM extension")
        return ModelFiles(entry=source, files=(source,))

    def parse_state(self, model: Path, value: object) -> dict:
        optional = {"camera", "mouthExpression", "blinkExpression", "motionTiming"}
        if not isinstance(value, dict) or set(value) - optional != {"expressions", "bones", "motion"}:
            raise ValueError("State requires expressions, bones and motion")
        expressions, bones, motion = value["expressions"], value["bones"], value["motion"]
        if not isinstance(expressions, dict) or not isinstance(bones, dict) or not isinstance(motion, str):
            raise ValueError("Invalid VRM state types")

        def number(item: object) -> bool:
            return type(item) in (int, float) and math.isfinite(item)

        for name, weight in expressions.items():
            if not isinstance(name, str) or not name or not number(weight) or not 0 <= weight <= 1:
                raise ValueError("Expression weights must be finite numbers in [0, 1]")
        for name, quaternion in bones.items():
            if (
                not isinstance(name, str) or not name
                or not isinstance(quaternion, (list, tuple)) or len(quaternion) != 4
                or not all(number(component) for component in quaternion)
                or abs(sum(component * component for component in quaternion) - 1) > 0.01
            ):
                raise ValueError("Bones require normalized local XYZW quaternions")
        if motion:
            source = package_file(model, motion)
            motion_document = read_glb(source)
            if source.suffix.lower() != ".vrma" or "VRMC_vrm_animation" not in motion_document["extensions"]:
                raise ValueError("Expected a VRMA animation")
        result = {
            "expressions": dict(expressions),
            "bones": {name: list(quaternion) for name, quaternion in bones.items()},
            "motion": motion,
        }
        if "motionTiming" in value:
            timing = value["motionTiming"]
            keys = ("entryStart", "bodyStart", "bodyEnd", "exitEnd")
            if not motion or not isinstance(timing, dict) or set(timing) != set(keys):
                raise ValueError("Motion timing requires all four boundaries and an animation")
            previous = 0
            for key in keys:
                seconds = timing[key]
                if not number(seconds) or seconds < previous:
                    raise ValueError("Motion boundaries must be finite, non-negative and ordered")
                previous = seconds
            try:
                duration = max(
                    motion_document["accessors"][sampler["input"]]["max"][0]
                    for sampler in motion_document["animations"][0]["samplers"]
                )
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise ValueError("Motion timing requires a readable animation duration") from error
            if not number(duration) or duration <= 0 or timing["exitEnd"] > duration + 0.001:
                raise ValueError("Motion timing exceeds the animation duration")
            result["motionTiming"] = dict(timing)
        if "camera" in value:
            camera = value["camera"]
            limits = {"yaw": (-180, 180), "pitch": (-80, 80), "zoom": (0.25, 4),
                      "panX": (-1, 1), "panY": (-1, 1)}
            if not isinstance(camera, dict) or set(camera) != set(limits):
                raise ValueError("Invalid model camera fields")
            for key, (minimum, maximum) in limits.items():
                if not number(camera[key]) or not minimum <= camera[key] <= maximum:
                    raise ValueError(f"Invalid model camera {key}")
            result["camera"] = dict(camera)
        for key in ("mouthExpression", "blinkExpression"):
            if key in value:
                if not isinstance(value[key], str) or len(value[key]) > 200:
                    raise ValueError("Invalid VRM expression binding")
                result[key] = value[key]
        return result

    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        return (package_file(model, state["motion"]),) if state["motion"] else ()

    def import_state(self, model: Path, source: Path, relative_path: str, base_state: object) -> dict:
        if source.suffix.lower() != ".vrma" or "VRMC_vrm_animation" not in read_glb(source)["extensions"]:
            raise ValueError("Expected a VRMA animation")
        base = self.parse_state(model, base_state)
        # The first validation pass runs against the external file, before the
        # shared importer copies it. The second pass validates the managed copy.
        if (
            not is_portable_relative_path(relative_path)
            or any(char in relative_path for char in "\\:?#%")
            or any(part in ("", ".", "..") for part in relative_path.split("/"))
            or not relative_path.lower().endswith(".vrma")
        ):
            raise ValueError("Invalid VRMA package path")
        # An imported clip has its own timeline, independent of the preview clip.
        base.pop("motionTiming", None)
        return {**base, "motion": relative_path}
