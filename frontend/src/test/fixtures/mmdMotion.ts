/** Minimal synthetic VMD with a single bone track, never derived from a user model. */
export function vmdBytes(boneName = new TextEncoder().encode("head")): ArrayBuffer {
  const buffer = new ArrayBuffer(50 + 4 + 2 * 111 + 4 + 16);
  const bytes = new Uint8Array(buffer);
  const data = new DataView(buffer);
  bytes.set(new TextEncoder().encode("Vocaloid Motion Data 0002"));
  bytes.set(new TextEncoder().encode("sample"), 30);
  data.setUint32(50, 2, true);
  for (const [index, frame] of [0, 30].entries()) {
    const offset = 54 + index * 111;
    bytes.set(boneName.slice(0, 15), offset);
    data.setUint32(offset + 15, frame, true);
    data.setFloat32(offset + 19 + 16, index ? Math.sin(0.3) : 0, true);
    data.setFloat32(offset + 19 + 24, index ? Math.cos(0.3) : 1, true);
    bytes.set(new Uint8Array([20, 20, 20, 20, 20, 20, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107]), offset + 47);
  }
  return buffer;
}

/** Exporter metadata accepted without affecting the SDK's bone evaluation. */
export function vmdExporterBytes(metadata: "model-name" | "interpolation-padding"): ArrayBuffer {
  const buffer = vmdBytes();
  const bytes = new Uint8Array(buffer);
  if (metadata === "model-name") {
    bytes.fill(0x61, 30, 49);
    bytes[49] = 0x82; // CP932 model label cut off halfway through a character.
  } else {
    for (let frame = 0; frame < 2; frame++) {
      const start = 54 + frame * 111 + 47;
      for (let index = 0; index < 64; index++) {
        if (index % 4 !== 0) bytes[start + index] = 0xff;
      }
    }
  }
  return buffer;
}
