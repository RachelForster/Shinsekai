"""Bounded PMX wire validation, independent of files, SDKs and resource banks."""

from __future__ import annotations

import math
import struct


class _Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def read(self, length: int) -> memoryview:
        if length < 0 or length > len(self.data) - self.offset:
            raise ValueError("Truncated PMX model")
        result = self.data[self.offset : self.offset + length]
        self.offset += length
        return result

    def number(self, fmt: str):
        return struct.unpack_from(fmt, self.read(struct.calcsize(fmt)))[0]

    def count(self, section: str, minimum_size: int, limit: int = 2_000_000) -> int:
        count = self.number("<i")
        if not 0 <= count <= limit or count * minimum_size > len(self.data) - self.offset:
            raise ValueError(f"Invalid PMX {section} count")
        return count

    def text(self, encoding: str) -> str:
        length = self.count("text length", 1, 1_000_000)
        return self.read(length).tobytes().decode(encoding)

    def floats(self, count: int) -> None:
        values = struct.unpack_from(f"<{count}f", self.read(4 * count))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite PMX geometry or parameters")

    def index(self, size: int, count: int | None = None, *, vertex: bool = False) -> int:
        fmt = {1: "<B", 2: "<H", 4: "<i"} if vertex else {1: "<b", 2: "<h", 4: "<i"}
        value = self.number(fmt[size])
        if value < (0 if vertex else -1) or (count is not None and value >= count):
            raise ValueError("Invalid PMX resource index")
        return value

    def enum(self, maximum: int) -> int:
        value = self.number("<B")
        if value > maximum:
            raise ValueError("Invalid PMX section type")
        return value


def texture_references(data: bytes) -> tuple[str, ...]:
    """Validate every mandatory section before returning package dependencies.

    Layout matches Babylon's PmxReader for PMX 2.0/2.1, including optional bone
    fields and variable morph/soft-body payloads. No runtime geometry is kept.
    """
    reader = _Reader(data)
    if reader.read(4).tobytes() != b"PMX ":
        raise ValueError("Expected a PMX model")
    version = reader.number("<f")
    if not any(math.isclose(version, supported, abs_tol=0.00001) for supported in (2.0, 2.1)):
        raise ValueError("Unsupported PMX version")
    if reader.number("<B") != 8:
        raise ValueError("Invalid PMX header")
    header = reader.read(8).tolist()
    encoding = "utf-16-le" if header[0] == 0 else "utf-8" if header[0] == 1 else None
    extra_uv, vertex_index, texture_index, material_index, bone_index, morph_index, rigid_index = header[1:]
    if encoding is None or extra_uv > 4 or any(size not in (1, 2, 4) for size in header[2:]):
        raise ValueError("Invalid PMX index or encoding settings")
    for _ in range(4):
        reader.text(encoding)

    vertex_count = reader.count("vertex", 37 + 16 * extra_uv + bone_index)
    if not vertex_count:
        raise ValueError("PMX has no vertices")
    max_skin_bone = -1
    for _ in range(vertex_count):
        reader.floats(8 + 4 * extra_uv)  # position, normal, UV and additional UVs
        skin = reader.enum(4)
        bone_slots = (1, 2, 4, 2, 4)[skin]
        for _ in range(bone_slots):
            max_skin_bone = max(max_skin_bone, reader.index(bone_index))
        reader.floats((0, 1, 4, 10, 4)[skin])
        reader.floats(1)  # edge scale
    face_count = reader.count("face index", vertex_index, 12_000_000)
    if not face_count or face_count % 3:
        raise ValueError("PMX requires triangle faces")
    face_data = reader.read(face_count * vertex_index)
    fmt = {1: "<B", 2: "<H", 4: "<i"}[vertex_index]
    if any(not 0 <= index < vertex_count for (index,) in struct.iter_unpack(fmt, face_data)):
        raise ValueError("Invalid PMX face vertex index")
    textures = tuple(reader.text(encoding) for _ in range(reader.count("texture", 4, 20_000)))

    material_count = reader.count("material", 84 + 2 * texture_index, 20_000)
    covered_faces = 0
    for _ in range(material_count):
        reader.text(encoding)
        reader.text(encoding)
        reader.floats(11)  # diffuse, specular, shininess, ambient
        reader.read(1)  # draw flags
        reader.floats(5)  # edge color/size
        reader.index(texture_index, len(textures))
        reader.index(texture_index, len(textures))
        reader.enum(3)  # sphere mode
        if reader.enum(1):
            reader.enum(9)  # shared toon texture 0..9
        else:
            reader.index(texture_index, len(textures))
        reader.text(encoding)
        count = reader.count("material face index", 0, face_count)
        if count % 3:
            raise ValueError("Invalid PMX material triangle count")
        covered_faces += count
    if not material_count or covered_faces != face_count:
        raise ValueError("PMX materials must cover all faces")

    bone_count = reader.count("bone", 26 + bone_index)
    if max_skin_bone >= bone_count:
        raise ValueError("Invalid PMX skin bone index")
    for _ in range(bone_count):
        reader.text(encoding)
        reader.text(encoding)
        reader.floats(3)
        reader.index(bone_index, bone_count)
        reader.read(4)  # transform order
        flags = reader.number("<H")
        if flags & 0x0001:
            reader.index(bone_index, bone_count)
        else:
            reader.floats(3)
        if flags & 0x0300:  # append rotation/translation
            reader.index(bone_index, bone_count)
            reader.floats(1)
        if flags & 0x0400:
            reader.floats(3)
        if flags & 0x0800:
            reader.floats(6)
        if flags & 0x2000:
            reader.read(4)
        if flags & 0x0020:
            reader.index(bone_index, bone_count)
            if reader.number("<i") < 0:
                raise ValueError("Invalid PMX IK iteration count")
            reader.floats(1)
            for _ in range(reader.count("IK link", bone_index + 1)):
                reader.index(bone_index, bone_count)
                if reader.enum(1):
                    reader.floats(6)

    # Impulse morphs reference rigid bodies, whose count occurs later.
    max_morph_rigid = -1
    morph_count = reader.count("morph", 14)
    for _ in range(morph_count):
        reader.text(encoding)
        reader.text(encoding)
        reader.enum(4)  # panel
        kind = reader.enum(10)
        for _ in range(reader.count("morph offset", 1)):
            if kind in (0, 9):
                reader.index(morph_index, morph_count)
                reader.floats(1)
            elif kind == 1 or 3 <= kind <= 7:
                reader.index(vertex_index, vertex_count, vertex=True)
                reader.floats(3 if kind == 1 else 4)
            elif kind == 2:
                reader.index(bone_index, bone_count)
                reader.floats(7)
            elif kind == 8:
                reader.index(material_index, material_count)
                reader.enum(1)
                reader.floats(28)
            else:  # impulse
                max_morph_rigid = max(max_morph_rigid, reader.index(rigid_index))
                reader.enum(1)
                reader.floats(6)

    for _ in range(reader.count("display frame", 13)):
        reader.text(encoding)
        reader.text(encoding)
        reader.enum(1)
        for _ in range(reader.count("display element", 2)):
            kind = reader.enum(1)
            reader.index(morph_index if kind else bone_index, morph_count if kind else bone_count)

    rigid_count = reader.count("rigid body", 69 + bone_index)
    if max_morph_rigid >= rigid_count:
        raise ValueError("Invalid PMX impulse rigid body index")
    for _ in range(rigid_count):
        reader.text(encoding)
        reader.text(encoding)
        reader.index(bone_index, bone_count)
        reader.enum(15)  # collision group
        reader.read(2)  # collision mask
        reader.enum(2)  # shape
        reader.floats(14)  # size, position, rotation, physical parameters
        reader.enum(2)  # physics mode
    for _ in range(reader.count("joint", 105 + 2 * rigid_index)):
        reader.text(encoding)
        reader.text(encoding)
        reader.enum(5)
        reader.index(rigid_index, rigid_count)
        reader.index(rigid_index, rigid_count)
        reader.floats(24)

    if version > 2.0:
        for _ in range(reader.count("soft body", 141 + material_index)):
            reader.text(encoding)
            reader.text(encoding)
            reader.enum(1)
            reader.index(material_index, material_count)
            reader.enum(15)
            reader.read(3)  # collision mask and flags
            reader.read(8)  # B-link distance and cluster count
            reader.floats(2)
            reader.read(4)  # aero model
            reader.floats(18)  # configuration and cluster coefficients
            reader.read(28)  # solver iterations and material settings
            for _ in range(reader.count("soft body anchor", rigid_index + vertex_index + 1)):
                reader.index(rigid_index, rigid_count)
                reader.index(vertex_index, vertex_count, vertex=True)
                reader.enum(1)
            for _ in range(reader.count("soft body pin", vertex_index)):
                reader.index(vertex_index, vertex_count, vertex=True)

    # Like Babylon, tolerate exporter-specific trailing metadata, but never
    # substitute it for a missing required section/count.
    return textures
