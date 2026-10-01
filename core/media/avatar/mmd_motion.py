"""Bounded validation of external MMD presets, without a rendering SDK."""

from __future__ import annotations

import math
import re
import stat
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MotionTargets:
    bones: frozenset[str]
    morphs: frozenset[str]


def _numbers(text: str, count: int) -> tuple[float, ...]:
    try:
        values = tuple(float(part.strip()) for part in text.split(","))
    except ValueError as error:
        raise ValueError("Invalid VPD parameters") from error
    if len(values) != count or not all(math.isfinite(number) for number in values):
        raise ValueError("Invalid VPD parameters")
    return values


def _quaternion(values: tuple[float, ...]) -> None:
    if sum(number * number for number in values) < 1e-12:
        raise ValueError("MMD rotation quaternion cannot be zero")


def _vpd(data: bytes) -> MotionTargets:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp932")
    text = re.sub(r"//[^\r\n]*", "", text)
    header = re.match(r"\s*Vocaloid Pose Data file\s+[^;]+;\s*(\d+)\s*;", text)
    if not header or int(header[1]) > 20_000:
        raise ValueError("Invalid VPD header")
    bones: set[str] = set()
    morphs: set[str] = set()
    indices: set[tuple[str, str]] = set()
    pattern = re.compile(r"\s*(Bone|Morph)(\d+)\{([^\r\n{}]+)\r?\n([^{}]*)\}")
    position = header.end()
    end = len(text.rstrip())
    while position < end:
        block = pattern.match(text, position)
        if not block:
            raise ValueError("Invalid or truncated VPD block")
        kind, index, name, payload = block.groups()
        name = name.strip()
        targets = bones if kind == "Bone" else morphs
        if not name or len(name) > 200 or name in targets or (kind, index) in indices:
            raise ValueError("Invalid or duplicate VPD target")
        fields = payload.strip().split(";")
        if fields[-1].strip() or len(fields) != (3 if kind == "Bone" else 2):
            raise ValueError("Invalid VPD parameters")
        if kind == "Bone":
            _numbers(fields[0], 3)
            _quaternion(_numbers(fields[1], 4))
        elif not 0 <= _numbers(fields[0], 1)[0] <= 1:
            raise ValueError("Invalid VPD morph weight")
        targets.add(name)
        indices.add((kind, index))
        if len(indices) > 20_000:
            raise ValueError("Too many VPD targets")
        position = block.end()
    if len(bones) != int(header[1]):
        raise ValueError("VPD bone count does not match its blocks")
    return MotionTargets(frozenset(bones), frozenset(morphs))


class _VmdReader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def read(self, size: int) -> memoryview:
        if size > len(self.data) - self.offset:
            raise ValueError("Truncated VMD motion")
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def count(self, stride: int) -> int:
        value = struct.unpack("<I", self.read(4))[0]
        if value > 1_000_000 or value * stride > len(self.data) - self.offset:
            raise ValueError("Invalid VMD keyframe count")
        return value

    def name(self, size: int) -> str:
        return self.read(size).tobytes().split(b"\0", 1)[0].decode("cp932")

    def frame(self) -> None:
        if struct.unpack("<I", self.read(4))[0] > 10_000_000:
            raise ValueError("Invalid VMD frame time")

    def floats(self, count: int) -> tuple[float, ...]:
        values = struct.unpack(f"<{count}f", self.read(4 * count))
        if not all(math.isfinite(number) for number in values):
            raise ValueError("Non-finite VMD parameters")
        return values

    def interpolation(self, size: int) -> None:
        if any(value > 127 for value in self.read(size)):
            raise ValueError("Invalid VMD interpolation")

    def flag(self) -> None:
        if self.read(1)[0] > 1:
            raise ValueError("Invalid VMD flag")


def _vmd(data: bytes) -> MotionTargets:
    reader = _VmdReader(data)
    if reader.read(30).tobytes().split(b"\0", 1)[0] != b"Vocaloid Motion Data 0002":
        raise ValueError("Expected a VMD 0002 motion")
    reader.name(20)
    bones: set[str] = set()
    morphs: set[str] = set()
    for _ in range(reader.count(111)):
        name = reader.name(15)
        if not name:
            raise ValueError("Empty VMD bone name")
        bones.add(name)
        reader.frame()
        reader.floats(3)
        _quaternion(reader.floats(4))
        reader.interpolation(64)
    for _ in range(reader.count(23)):
        name = reader.name(15)
        if not name:
            raise ValueError("Empty VMD morph name")
        morphs.add(name)
        reader.frame()
        if not 0 <= reader.floats(1)[0] <= 1:
            raise ValueError("Invalid VMD morph weight")
    # MMD exporters may omit trailing sections, but a present section must be complete.
    for section, stride in (("camera", 61), ("light", 28), ("shadow", 9), ("property", 9)):
        if reader.offset == len(data):
            break
        for _ in range(reader.count(stride)):
            reader.frame()
            if section == "camera":
                reader.floats(7)
                reader.interpolation(24)
                reader.read(4)
                reader.flag()
            elif section == "light":
                reader.floats(6)
            elif section == "shadow":
                if reader.read(1)[0] > 2:
                    raise ValueError("Invalid VMD shadow mode")
                reader.floats(1)
            else:
                reader.flag()
                for _ in range(reader.count(21)):
                    reader.name(20)
                    reader.flag()
    if reader.offset != len(data):
        raise ValueError("Unexpected VMD trailing data")
    return MotionTargets(frozenset(bones), frozenset(morphs))


def inspect_motion(source: Path) -> MotionTargets:
    parsers = {".vpd": _vpd, ".vmd": _vmd}
    parser = parsers.get(source.suffix.lower())
    if parser is None:
        raise ValueError("MMD presets require .vpd or .vmd")
    try:
        metadata = source.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("MMD preset must be a regular file")
        if metadata.st_size > 64 * 1024 * 1024:
            raise ValueError("MMD preset exceeds 64 MiB")
        result = parser(source.read_bytes())
    except OSError as error:
        raise ValueError("Cannot read MMD preset file") from error
    except UnicodeDecodeError as error:
        raise ValueError("Invalid MMD preset text encoding") from error
    if not result.bones and not result.morphs:
        raise ValueError("MMD preset has no bone or morph tracks")
    return result
