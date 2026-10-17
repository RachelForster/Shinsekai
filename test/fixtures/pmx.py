"""Small synthetic PMX packages, with explicit boundaries for corruption tests."""

import struct


def pmx_sections(texture="", *, version=2.0, index_size=1, encoding=1,
                 vertex_count=3, skin=0, rich=False):
    def text(value):
        encoded = value.encode("utf-8" if encoding else "utf-16-le")
        return struct.pack("<i", len(encoded)) + encoded

    def integer(value):
        return struct.pack("<i", value)

    def index(value, *, vertex=False):
        fmt = {1: "B", 2: "H", 4: "i"} if vertex else {1: "b", 2: "h", 4: "i"}
        return struct.pack("<" + fmt[index_size], value)

    def floats(*values):
        return struct.pack(f"<{len(values)}f", *values)

    extra_uv = 4 if rich else 0
    header = (b"PMX " + struct.pack("<fB", version, 8)
              + bytes((encoding, extra_uv, *([index_size] * 6))) + text("sample") * 4)
    vertices = integer(vertex_count)
    for position in ((0, 0, 0), (1, 0, 0), (0, 1, 0))[:vertex_count]:
        vertices += floats(*position, 0, 0, 1, 0, 0, *([0] * (4 * extra_uv))) + bytes((skin,))
        vertices += index(0) * (1, 2, 4, 2, 4)[skin]
        vertices += floats(*([1] + [0] * ((0, 1, 4, 10, 4)[skin] - 1))) if skin else b""
        vertices += floats(1)
    faces = integer(3) + b"".join(index(i, vertex=True) for i in range(3)) if vertex_count else integer(0)
    textures = integer(1) + text(texture)
    materials = (integer(1) + text("material") + text("") + floats(1, 1, 1, 1, *([0] * 7))
                 + b"\x00" + floats(*([0] * 5)) + index(0) + index(-1)
                 + b"\x00\x01\x00" + text("") + integer(3))
    if not vertex_count:
        materials = integer(0)
    bones = (integer(2 if rich else 1) + text("root") + text("") + floats(0, 0, 0)
             + index(-1) + integer(0) + struct.pack("<H", 2) + floats(0, 1, 0))
    if rich:
        bones += (text("head") + text("") + floats(0, 1, 0) + index(0) + integer(1)
                  + struct.pack("<H", 0x2F23) + index(-1)  # indexed tail and all optional fields
                  + index(0) + floats(0.5) + floats(0, 1, 0) + floats(1, 0, 0, 0, 0, 1)
                  + integer(0) + index(0) + integer(1) + floats(0.5)
                  + integer(1) + index(0) + b"\x01" + floats(*([0] * 6)))
    morphs = integer(11 if rich else 0)
    if rich:
        for kind in range(11):
            morphs += text(f"morph-{kind}") + text("") + bytes((4, kind)) + integer(1)
            if kind in (0, 9):
                morphs += index(1) + floats(0.5)
            elif kind == 1 or 3 <= kind <= 7:
                morphs += index(0, vertex=True) + floats(*([0] * (3 if kind == 1 else 4)))
            elif kind == 2:
                morphs += index(0) + floats(0, 0, 0, 0, 0, 0, 1)
            elif kind == 8:
                morphs += index(-1) + b"\x01" + floats(*([0] * 28))
            else:
                morphs += index(0) + b"\x00" + floats(*([0] * 6))
    display = (integer(1) + text("Root") + text("") + b"\x01" + integer(2 if rich else 1)
               + b"\x00" + index(0) + (b"\x01" + index(1) if rich else b""))
    rigid = integer(1 if rich else 0)
    joints = integer(1 if rich else 0)
    if rich:
        rigid += (text("body") + text("") + index(0) + b"\x00\x00\x00\x00"
                  + floats(1, 1, 1, *([0] * 11)) + b"\x00")
        joints += text("joint") + text("") + b"\x00" + index(0) * 2 + floats(*([0] * 24))
    sections = dict(header=header, vertices=vertices, faces=faces, textures=textures,
                    materials=materials, bones=bones, morphs=morphs, display=display,
                    rigid=rigid, joints=joints)
    if version > 2.0:
        soft = integer(1 if rich else 0)
        if rich:
            soft += (text("soft") + text("") + b"\x00" + index(0) + b"\x00\x00\x00\x00"
                     + integer(0) * 2 + floats(1, 0) + integer(0) + floats(*([0] * 18))
                     + integer(0) * 7 + integer(1) + index(0) + index(0, vertex=True)
                     + b"\x00" + integer(1) + index(1, vertex=True))
        sections["soft"] = soft
    return sections


def pmx_bytes(texture="", **options):
    return b"".join(pmx_sections(texture, **options).values())
