"""PMX model package and morph-state adapter for Babylon MMD."""

from __future__ import annotations

import math
import struct
from functools import lru_cache
from pathlib import Path

from sdk.adapters import ModelAssetAdapter, ModelCapabilities, ModelFiles
from sdk.path_utils import is_portable_relative_path, safe_child_path


class _PmxReader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def read(self, length: int) -> memoryview:
        if length < 0 or length > len(self.data) - self.offset:
            raise ValueError("Truncated PMX model")
        result = self.data[self.offset : self.offset + length]
        self.offset += length
        return result

    def number(self, fmt: str) -> int:
        size = struct.calcsize(fmt)
        return struct.unpack_from(fmt, self.read(size))[0]

    def text(self, encoding: str) -> str:
        length = self.number("<i")
        if length < 0 or length > 1_000_000:
            raise ValueError("Invalid PMX text length")
        return self.read(length).tobytes().decode(encoding)


@lru_cache(maxsize=128)
def _cached_texture_paths(model: Path, mtime_ns: int, size: int) -> tuple[Path, ...]:
    # model_file authorizes every texture request independently; avoid parsing
    # the same (potentially large) PMX once per image.
    _ = (mtime_ns, size)
    reader = _PmxReader(model.read_bytes())
    if reader.read(4).tobytes() != b"PMX ":
        raise ValueError("Expected a PMX model")
    version = reader.number("<f")
    if not (1.9 <= version <= 2.1):
        raise ValueError("Unsupported PMX version")
    header_length = reader.number("<B")
    if header_length != 8:
        raise ValueError("Invalid PMX header")
    header = reader.read(8).tolist()
    encoding = "utf-16-le" if header[0] == 0 else "utf-8" if header[0] == 1 else None
    extra_uv, vertex_index, texture_index, material_index, bone_index, morph_index, rigid_index = header[1:]
    if encoding is None or extra_uv > 4 or any(size not in (1, 2, 4) for size in header[2:]):
        raise ValueError("Invalid PMX index or encoding settings")
    # Header index sizes are required for the vertex and face sections; the
    # remaining sizes are validated here even though they occur later.
    _ = (texture_index, material_index, morph_index, rigid_index)
    for _ in range(4):
        reader.text(encoding)
    vertex_count = reader.number("<i")
    if not 0 <= vertex_count <= 2_000_000:
        raise ValueError("Invalid PMX vertex count")
    for _ in range(vertex_count):
        reader.read(32 + 16 * extra_uv)
        skin = reader.number("<B")
        if skin == 0:  # BDEF1
            reader.read(bone_index)
        elif skin == 1:  # BDEF2
            reader.read(2 * bone_index + 4)
        elif skin == 2 or skin == 4:  # BDEF4 / QDEF
            reader.read(4 * bone_index + 16)
        elif skin == 3:  # SDEF
            reader.read(2 * bone_index + 4 + 36)
        else:
            raise ValueError("Invalid PMX skinning type")
        reader.read(4)  # edge scale
    face_index_count = reader.number("<i")
    if not 0 <= face_index_count <= 12_000_000:
        raise ValueError("Invalid PMX face count")
    reader.read(face_index_count * vertex_index)
    texture_count = reader.number("<i")
    if not 0 <= texture_count <= 20_000:
        raise ValueError("Invalid PMX texture count")
    paths: list[Path] = []
    for _ in range(texture_count):
        raw = reader.text(encoding).replace("\\", "/")
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
