/**
 * Pure TypeScript ZIP reader/writer (STORE + DEFLATE-RAW via Web Compression Streams API).
 * Zero external dependencies so standalone Toy & Mobile builds require no extra npm packages.
 */

const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder("utf-8", { fatal: false });

export function sanitizeZipMemberPath(rawPath: string): string {
  let normalized = rawPath.replace(/\\/g, "/").trim();
  while (normalized.startsWith("./")) {
    normalized = normalized.slice(2);
  }
  normalized = normalized.replace(/\/+$/, "");
  if (!normalized) {
    return "";
  }
  if (
    normalized.includes("\0") ||
    normalized.startsWith("/") ||
    /^[A-Za-z]:/.test(normalized)
  ) {
    throw new Error(`Unsafe ZIP entry path rejected: ${rawPath}`);
  }
  const parts = normalized.split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) {
    throw new Error(`Invalid ZIP entry path component: ${rawPath}`);
  }
  return parts.join("/");
}

async function runStreamTransform(
  bytes: Uint8Array,
  stream: TransformStream<Uint8Array, Uint8Array>,
): Promise<Uint8Array> {
  const writer = stream.writable.getWriter();
  const safeCopy = new Uint8Array(bytes.byteLength);
  safeCopy.set(bytes);
  const writePromise = writer.write(safeCopy).then(() => writer.close());

  const reader = stream.readable.getReader();
  const chunks: Uint8Array[] = [];
  let totalLength = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      chunks.push(value);
      totalLength += value.byteLength;
    }
  }
  await writePromise;

  const out = new Uint8Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

async function deflateRawIfBeneficial(
  bytes: Uint8Array,
): Promise<{ method: 0 | 8; payload: Uint8Array }> {
  if (bytes.byteLength < 64 || typeof CompressionStream === "undefined") {
    return { method: 0, payload: bytes };
  }
  try {
    const compressed = await runStreamTransform(
      bytes,
      new CompressionStream("deflate-raw") as unknown as TransformStream<Uint8Array, Uint8Array>,
    );
    if (compressed.byteLength < bytes.byteLength) {
      return { method: 8, payload: compressed };
    }
  } catch {
    // Fall back cleanly to STORE when runtime lacks deflate-raw support.
  }
  return { method: 0, payload: bytes };
}

async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream === "undefined") {
    throw new Error("Current runtime does not support deflate-raw ZIP decompression.");
  }
  return runStreamTransform(
    bytes,
    new DecompressionStream("deflate-raw") as unknown as TransformStream<Uint8Array, Uint8Array>,
  );
}

function readUint16(view: DataView, offset: number): number {
  return view.getUint16(offset, true);
}

function readUint32(view: DataView, offset: number): number {
  return view.getUint32(offset, true);
}

export async function unzipEntries(input: Uint8Array | ArrayBuffer): Promise<Map<string, Uint8Array>> {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (bytes.byteLength < 22) {
    throw new Error("Invalid ZIP archive: file too small.");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  // Locate End of Central Directory record (PK\x05\x06)
  const minOffset = Math.max(0, bytes.byteLength - 65557);
  let eocdOffset = -1;
  for (let i = bytes.byteLength - 22; i >= minOffset; i -= 1) {
    if (readUint32(view, i) === 0x06054b50) {
      eocdOffset = i;
      break;
    }
  }
  if (eocdOffset < 0) {
    throw new Error("Invalid ZIP archive: missing End of Central Directory signature.");
  }

  const entryCount = readUint16(view, eocdOffset + 10);
  const cdOffset = readUint32(view, eocdOffset + 16);
  const results = new Map<string, Uint8Array>();

  let cursor = cdOffset;
  for (let idx = 0; idx < entryCount; idx += 1) {
    if (cursor + 46 > bytes.byteLength || readUint32(view, cursor) !== 0x02014b50) {
      throw new Error("Invalid ZIP archive: corrupt Central Directory entry.");
    }
    const method = readUint16(view, cursor + 10);
    const compressedSize = readUint32(view, cursor + 20);
    const uncompressedSize = readUint32(view, cursor + 24);
    const nameLen = readUint16(view, cursor + 28);
    const extraLen = readUint16(view, cursor + 30);
    const commentLen = readUint16(view, cursor + 32);
    const localHeaderOffset = readUint32(view, cursor + 42);

    const rawName = textDecoder.decode(bytes.subarray(cursor + 46, cursor + 46 + nameLen));
    cursor += 46 + nameLen + extraLen + commentLen;

    const isDir = rawName.endsWith("/") || rawName.endsWith("\\");
    const safePath = sanitizeZipMemberPath(rawName);
    if (!safePath || isDir) {
      continue;
    }

    if (
      localHeaderOffset + 30 > bytes.byteLength ||
      readUint32(view, localHeaderOffset) !== 0x04034b50
    ) {
      throw new Error(`Invalid ZIP local header for entry: ${safePath}`);
    }
    const localNameLen = readUint16(view, localHeaderOffset + 26);
    const localExtraLen = readUint16(view, localHeaderOffset + 28);
    const dataStart = localHeaderOffset + 30 + localNameLen + localExtraLen;
    const dataEnd = dataStart + compressedSize;
    if (dataEnd > bytes.byteLength) {
      throw new Error(`Truncated ZIP entry payload: ${safePath}`);
    }

    const compressedSlice = bytes.subarray(dataStart, dataEnd);
    let outputBytes: Uint8Array;
    if (method === 0) {
      outputBytes = compressedSlice.slice();
    } else if (method === 8) {
      outputBytes = await inflateRaw(compressedSlice);
    } else {
      throw new Error(`Unsupported ZIP compression method ${method} for entry: ${safePath}`);
    }

    if (uncompressedSize > 0 && outputBytes.byteLength !== uncompressedSize) {
      throw new Error(`ZIP entry size mismatch for ${safePath}`);
    }

    results.set(safePath, outputBytes);
  }

  return results;
}

export async function zipEntries(entries: Record<string, Uint8Array>): Promise<Uint8Array> {
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let localOffset = 0;
  let centralLength = 0;
  let fileCount = 0;

  for (const [rawPath, rawBytes] of Object.entries(entries)) {
    const safePath = sanitizeZipMemberPath(rawPath);
    if (!safePath) continue;

    const nameBytes = textEncoder.encode(safePath);
    const fileCrc = crc32(rawBytes);
    const { method, payload } = await deflateRawIfBeneficial(rawBytes);

    // Local File Header (30 bytes + name)
    const localHeader = new Uint8Array(30 + nameBytes.length);
    const ldv = new DataView(localHeader.buffer);
    ldv.setUint32(0, 0x04034b50, true);
    ldv.setUint16(4, 20, true); // version needed: 2.0
    ldv.setUint16(6, 0x0800, true); // UTF-8 filename flag
    ldv.setUint16(8, method, true);
    ldv.setUint16(10, 0, true);
    ldv.setUint16(12, 0x5421, true);
    ldv.setUint32(14, fileCrc, true);
    ldv.setUint32(18, payload.byteLength, true);
    ldv.setUint32(22, rawBytes.byteLength, true);
    ldv.setUint16(26, nameBytes.length, true);
    ldv.setUint16(28, 0, true);
    localHeader.set(nameBytes, 30);

    localParts.push(localHeader, payload);

    // Central Directory Header (46 bytes + name)
    const cdHeader = new Uint8Array(46 + nameBytes.length);
    const cdv = new DataView(cdHeader.buffer);
    cdv.setUint32(0, 0x02014b50, true);
    cdv.setUint16(4, 20, true);
    cdv.setUint16(6, 20, true);
    cdv.setUint16(8, 0x0800, true);
    cdv.setUint16(10, method, true);
    cdv.setUint16(12, 0, true);
    cdv.setUint16(14, 0x5421, true);
    cdv.setUint32(16, fileCrc, true);
    cdv.setUint32(20, payload.byteLength, true);
    cdv.setUint32(24, rawBytes.byteLength, true);
    cdv.setUint16(28, nameBytes.length, true);
    cdv.setUint16(30, 0, true);
    cdv.setUint16(32, 0, true);
    cdv.setUint16(34, 0, true);
    cdv.setUint16(36, 0, true);
    cdv.setUint32(38, 0, true);
    cdv.setUint32(42, localOffset, true);
    cdHeader.set(nameBytes, 46);

    centralParts.push(cdHeader);
    centralLength += cdHeader.byteLength;
    localOffset += localHeader.byteLength + payload.byteLength;
    fileCount += 1;
  }

  // End of Central Directory (22 bytes)
  const eocd = new Uint8Array(22);
  const edv = new DataView(eocd.buffer);
  edv.setUint32(0, 0x06054b50, true);
  edv.setUint16(4, 0, true);
  edv.setUint16(6, 0, true);
  edv.setUint16(8, fileCount, true);
  edv.setUint16(10, fileCount, true);
  edv.setUint32(12, centralLength, true);
  edv.setUint32(16, localOffset, true);
  edv.setUint16(20, 0, true);

  const totalSize = localOffset + centralLength + eocd.byteLength;
  const archive = new Uint8Array(totalSize);
  let writePos = 0;
  for (const part of localParts) {
    archive.set(part, writePos);
    writePos += part.byteLength;
  }
  for (const part of centralParts) {
    archive.set(part, writePos);
    writePos += part.byteLength;
  }
  archive.set(eocd, writePos);
  return archive;
}
