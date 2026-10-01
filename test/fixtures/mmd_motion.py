"""Small, redistributable synthetic MMD motion/pose files."""

import struct


def vpd_bytes(name="root", *, encoding="utf-8", angle="0,0.258819,0,0.965926"):
    return ("Vocaloid Pose Data file\n\nsample.osm;\n1;\n"
            f"Bone0{{{name}\n0,0,0;\n{angle};\n}}\n").encode(encoding)


def vmd_bytes(name="root", *, morph="", optional=True):
    def field(value, size):
        return value.encode("cp932").ljust(size, b"\0")
    header = b"Vocaloid Motion Data 0002".ljust(30, b"\0") + field("sample", 20)
    bone = b""
    for frame, quat in ((0, (0, 0, 0, 1)), (30, (0, 0.258819, 0, 0.965926))):
        bone += field(name, 15) + struct.pack("<I7f", frame, 0, 0, 0, *quat) + bytes([20] * 16 + [107] * 16 + [0] * 32)
    result = header + struct.pack("<I", 2) + bone + struct.pack("<I", int(bool(morph)))
    if morph:
        result += field(morph, 15) + struct.pack("<If", 0, 0.5)
    return result + (struct.pack("<4I", 0, 0, 0, 0) if optional else b"")
