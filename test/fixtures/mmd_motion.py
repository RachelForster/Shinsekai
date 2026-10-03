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
    controls = bytes([20] * 8 + [107] * 8)
    interpolation = b"".join(controls[axis:] + bytes(axis) for axis in range(4))
    for frame, quat in ((0, (0, 0, 0, 1)), (30, (0, 0.258819, 0, 0.965926))):
        bone += field(name, 15) + struct.pack("<I7f", frame, 0, 0, 0, *quat) + interpolation
    result = header + struct.pack("<I", 2) + bone + struct.pack("<I", int(bool(morph)))
    if morph:
        result += field(morph, 15) + struct.pack("<If", 0, 0.5)
    return result + (struct.pack("<4I", 0, 0, 0, 0) if optional else b"")


def vmd_exporter_bytes(name="root", *, metadata):
    """Valid motion with exporter metadata the rendering SDK does not use."""
    data = bytearray(vmd_bytes(name))
    if metadata == "model-name":
        data[30:50] = b"a" * 19 + b"\x82"  # Truncated CP932 model label.
    elif metadata == "interpolation-padding":
        for frame in range(2):
            start = 54 + frame * 111 + 47
            for index in range(16, 64):
                if index % 4:
                    data[start + index] = 0xff
    else:
        raise ValueError(f"Unknown VMD metadata fixture: {metadata}")
    return bytes(data)
