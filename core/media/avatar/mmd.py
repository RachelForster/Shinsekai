"""PMX model package and morph-state adapter for Babylon MMD."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from sdk.adapters import ModelAssetAdapter, ModelCapabilities, ModelFiles
from sdk.path_utils import is_portable_relative_path, safe_child_path
from core.media.avatar.pmx import inspect_pmx, PmxInspection
from core.media.avatar.mmd_motion import inspect_motion


@lru_cache(maxsize=128)
def _metadata(model: Path, mtime_ns: int, size: int) -> PmxInspection:
    return inspect_pmx(model.read_bytes())


def _validate_motion(model: Path, source: Path) -> None:
    # Only mutation/package-validation paths parse presets; never retain the
    # full target-name sets in a long-lived authorization cache.
    targets = inspect_motion(source)
    stat = model.stat()
    known = _metadata(model, stat.st_mtime_ns, stat.st_size)
    if not (targets.bones & known.bones or targets.morphs & known.morphs):
        raise ValueError("MMD preset has no tracks matching this model")


@lru_cache(maxsize=128)
def _cached_texture_paths(model: Path, mtime_ns: int, size: int) -> tuple[Path, ...]:
    # model_file authorizes every texture request independently; avoid parsing
    # the same (potentially large) PMX once per image.
    _ = (mtime_ns, size)
    paths: list[Path] = []
    for texture in _metadata(model, mtime_ns, size).textures:
        raw = texture.replace("\\", "/")
        if not raw:
            continue
        if (
            not is_portable_relative_path(raw)
            or any(char in raw for char in ":?#%")
            or any(part in ("", ".", "..") for part in raw.split("/"))
        ):
            raise ValueError("PMX texture must be a relative package path")
        path = safe_child_path(model.parent, raw)
        if not path.is_file():
            raise FileNotFoundError(raw)
        paths.append(path)
    return tuple(dict.fromkeys(paths))


def _texture_paths(model: Path) -> tuple[Path, ...]:
    stat = model.stat()
    return _cached_texture_paths(model, stat.st_mtime_ns, stat.st_size)


class MmdAdapter(ModelAssetAdapter):
    format_id = "mmd"
    capabilities = ModelCapabilities(mouth=True, blink=True, motion=True)

    def inspect(self, source: Path) -> ModelFiles:
        source = source.resolve(strict=True)
        if source.is_dir():
            entries = list(source.rglob("*.pmx"))
            if len(entries) != 1:
                raise ValueError("Select one .pmx explicitly")
            source = entries[0]
        if source.suffix.lower() != ".pmx":
            raise ValueError("MMD requires a .pmx entry")
        return ModelFiles(entry=source, files=(source, *_texture_paths(source)))

    def parse_state(self, model: Path, value: object) -> dict:
        if not isinstance(value, dict) or set(value) - {"camera", "motion"} != {"morphs", "mouthMorph", "blinkMorph"}:
            raise ValueError("MMD state requires morphs, mouthMorph, blinkMorph")
        morphs = value["morphs"]
        if not isinstance(morphs, dict) or len(morphs) > 512:
            raise ValueError("Invalid MMD morphs")
        for name, weight in morphs.items():
            if (
                not isinstance(name, str) or not name or len(name) > 200
                or not isinstance(weight, (int, float)) or isinstance(weight, bool)
                or not math.isfinite(weight) or not 0 <= weight <= 1
            ):
                raise ValueError("MMD morph weights must be finite numbers between 0 and 1")
        for key in ("mouthMorph", "blinkMorph"):
            if not isinstance(value[key], str) or len(value[key]) > 200:
                raise ValueError(f"Invalid MMD {key}")
        camera = value.get("camera", {"yaw": 0, "pitch": 0, "zoom": 1, "panX": 0, "panY": 0})
        limits = {"yaw": (-180, 180), "pitch": (-80, 80), "zoom": (0.25, 4), "panX": (-1, 1), "panY": (-1, 1)}
        if not isinstance(camera, dict) or set(camera) != set(limits):
            raise ValueError("Invalid MMD camera fields")
        for key, (minimum, maximum) in limits.items():
            number = camera[key]
            if (not isinstance(number, (int, float)) or isinstance(number, bool)
                    or not math.isfinite(number) or not minimum <= number <= maximum):
                raise ValueError(f"Invalid MMD camera {key}")
        # The loader, not the backend file route, owns semantic morph names.
        self.inspect(model)
        result = {"morphs": dict(morphs), "mouthMorph": value["mouthMorph"], "blinkMorph": value["blinkMorph"], "camera": dict(camera)}
        motion = value.get("motion", "")
        if not isinstance(motion, str):
            raise ValueError("Invalid MMD motion path")
        if motion:
            if (not is_portable_relative_path(motion) or any(char in motion for char in "\\:?#%")
                    or any(ord(char) < 32 for char in motion)
                    or any(part in ("", ".", "..") for part in motion.split("/"))):
                raise ValueError("MMD motion must be a relative package path")
            source = safe_child_path(model.parent, motion)
            _validate_motion(model, source)
            result["motion"] = motion
        return result

    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        return (safe_child_path(model.parent, state["motion"]),) if state.get("motion") else ()

    def import_state(self, model: Path, source: Path, relative_path: str, base_state: object) -> dict:
        _validate_motion(model, source)
        base = self.parse_state(model, base_state)
        return {**base, "motion": relative_path}
