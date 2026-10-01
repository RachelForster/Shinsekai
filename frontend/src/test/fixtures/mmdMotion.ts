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
