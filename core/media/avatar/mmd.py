"""PMX model package and morph-state adapter for Babylon MMD."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from sdk.adapters import ModelAssetAdapter, ModelCapabilities, ModelFiles
from sdk.path_utils import is_portable_relative_path, safe_child_path
from core.media.avatar.pmx import texture_references


@lru_cache(maxsize=128)
def _cached_texture_paths(model: Path, mtime_ns: int, size: int) -> tuple[Path, ...]:
    # model_file authorizes every texture request independently; avoid parsing
    # the same (potentially large) PMX once per image.
    _ = (mtime_ns, size)
    paths: list[Path] = []
    for texture in texture_references(model.read_bytes()):
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
    capabilities = ModelCapabilities(mouth=True, blink=True)

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
        if not isinstance(value, dict) or set(value) - {"camera"} != {"morphs", "mouthMorph", "blinkMorph"}:
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
        return {"morphs": dict(morphs), "mouthMorph": value["mouthMorph"], "blinkMorph": value["blinkMorph"], "camera": dict(camera)}

    def state_files(self, model: Path, state: dict) -> tuple[Path, ...]:
        return ()
