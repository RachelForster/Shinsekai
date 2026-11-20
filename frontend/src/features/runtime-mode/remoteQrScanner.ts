export interface ParsedRemoteBridgeQr {
  url: string;
  token: string;
}

interface BarcodeDetectorResultItem {
  rawValue?: string;
}

interface BarcodeDetectorInstance {
  detect(source: CanvasImageSource): Promise<BarcodeDetectorResultItem[]>;
}

interface BarcodeDetectorConstructor {
  new (options?: { formats?: string[] }): BarcodeDetectorInstance;
  getSupportedFormats?: () => Promise<string[]>;
}

declare global {
  interface Window {
    __SHINSEKAI_ANDROID_QR__?: {
      decodeImageDataUrl: (dataUrl: string) => string;
    };
    BarcodeDetector?: BarcodeDetectorConstructor;
  }
}

const INVALID_QR_ERROR = "二维码中未包含有效的新世界电脑端连接地址。";
const LOOPBACK_QR_ERROR = "该二维码是本机回环地址，手机无法访问；请扫描电脑端开启「手机访问」后弹出的局域网二维码。";

let cachedDetector: BarcodeDetectorInstance | null = null;
let cachedDetectorCtor: BarcodeDetectorConstructor | undefined;
let detectorSupportPromise: Promise<boolean> | null = null;

function parseIpv4Octets(host: string): [number, number, number, number] | null {
  const parts = host.split(".");
  if (parts.length !== 4) {
    return null;
  }
  const octets: number[] = [];
  for (const part of parts) {
    if (!/^(?:0|[1-9]\d{0,2})$/.test(part)) {
      return null;
    }
    const val = Number(part);
    if (!Number.isInteger(val) || val < 0 || val > 255) {
      return null;
    }
    octets.push(val);
  }
  return [octets[0], octets[1], octets[2], octets[3]];
}

function isLoopbackOrUnspecifiedIpv4(octets: [number, number, number, number]): boolean {
  const [a, b, c, d] = octets;
  return a === 127 || (a === 0 && b === 0 && c === 0 && d === 0);
}

function parseIpv6GroupSlice(parts: string[]): number[] | null {
  const hextets: number[] = [];
  for (let i = 0; i < parts.length; i += 1) {
    const part = parts[i];
    if (!part) {
      return null;
    }
    if (part.includes(".")) {
      if (i !== parts.length - 1) {
        return null;
      }
      const ipv4 = parseIpv4Octets(part);
      if (!ipv4) {
        return null;
      }
      hextets.push((ipv4[0] << 8) | ipv4[1], (ipv4[2] << 8) | ipv4[3]);
      continue;
    }
    if (!/^[0-9a-f]{1,4}$/i.test(part)) {
      return null;
    }
    hextets.push(parseInt(part, 16));
  }
  return hextets;
}

function parseIpv6Hextets(host: string): number[] | null {
  if (!host.includes(":")) {
    return null;
  }
  const doubleColonParts = host.split("::");
  if (doubleColonParts.length > 2) {
    return null;
  }

  if (doubleColonParts.length === 1) {
    const hextets = parseIpv6GroupSlice(host.split(":"));
    return hextets && hextets.length === 8 ? hextets : null;
  }

  const [leftRaw, rightRaw] = doubleColonParts;
  const left = leftRaw ? parseIpv6GroupSlice(leftRaw.split(":")) : [];
  const right = rightRaw ? parseIpv6GroupSlice(rightRaw.split(":")) : [];
  if (!left || !right) {
    return null;
  }
  const zeroCount = 8 - (left.length + right.length);
  if (zeroCount < 1) {
    return null;
  }
  return [...left, ...Array<number>(zeroCount).fill(0), ...right];
}

export function isLoopbackHostname(rawHostname: string): boolean {
  let host = rawHostname.trim().toLowerCase();
  if (host.startsWith("[") && host.endsWith("]")) {
    host = host.slice(1, -1);
  }
  const zoneIdx = host.indexOf("%");
  if (zoneIdx >= 0) {
    host = host.slice(0, zoneIdx);
  }
  host = host.replace(/\.+$/, "");
  if (!host) {
    return false;
  }
  if (host === "localhost" || host.endsWith(".localhost")) {
    return true;
  }

  const ipv4 = parseIpv4Octets(host);
  if (ipv4) {
    return isLoopbackOrUnspecifiedIpv4(ipv4);
  }

  const hextets = parseIpv6Hextets(host);
  if (!hextets) {
    return false;
  }

  const isPrefixZero = (endExclusive: number) => hextets.slice(0, endExclusive).every((h) => h === 0);
  // :: (unspecified) and ::1 (IPv6 loopback)
  if (isPrefixZero(7) && (hextets[7] === 0 || hextets[7] === 1)) {
    return true;
  }

  // IPv4-mapped (::ffff:0:0/96), IPv4-translated (::ffff:0:0:0/96), and IPv4-compatible (::/96)
  const isEmbeddedIpv4 =
    (isPrefixZero(5) && hextets[5] === 0xffff) ||
    (isPrefixZero(4) && hextets[4] === 0xffff && hextets[5] === 0) ||
    isPrefixZero(6);
  if (isEmbeddedIpv4) {
    const embedded: [number, number, number, number] = [
      (hextets[6] >> 8) & 0xff,
      hextets[6] & 0xff,
      (hextets[7] >> 8) & 0xff,
      hextets[7] & 0xff,
    ];
    return isLoopbackOrUnspecifiedIpv4(embedded);
  }

  return false;
}

function validateNonLoopbackHttpUrl(rawUrl: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error(INVALID_QR_ERROR);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(INVALID_QR_ERROR);
  }
  const hostname = parsed.hostname.toLowerCase();
  if (!hostname) {
    throw new Error(INVALID_QR_ERROR);
  }
  if (isLoopbackHostname(hostname)) {
    throw new Error(LOOPBACK_QR_ERROR);
  }
  return parsed;
}

function normalizeHttpCandidate(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (/^(?:[a-z0-9.-]+|\[[0-9a-f:.]+\]):\d{2,5}(?:\/.*)?$/i.test(trimmed)) {
    return `http://${trimmed}`;
  }
  return trimmed;
}

function parseHttpUrlPayload(rawUrl: string, fallbackToken = ""): ParsedRemoteBridgeQr {
  const parsed = validateNonLoopbackHttpUrl(normalizeHttpCandidate(rawUrl));
  const hashQueryIdx = parsed.hash.indexOf("?");
  const hashParams = hashQueryIdx >= 0 ? new URLSearchParams(parsed.hash.slice(hashQueryIdx + 1)) : null;

  const explicitBridge = (
    parsed.searchParams.get("shinsekai_bridge") ||
    parsed.searchParams.get("bridge") ||
    hashParams?.get("shinsekai_bridge") ||
    ""
  ).trim();

  const resolvedUrl = explicitBridge ? validateNonLoopbackHttpUrl(normalizeHttpCandidate(explicitBridge)) : parsed;

  const token = (
    parsed.searchParams.get("shinsekai_bridge_token") ||
    parsed.searchParams.get("token") ||
    parsed.searchParams.get("bridgeToken") ||
    hashParams?.get("shinsekai_bridge_token") ||
    hashParams?.get("token") ||
    fallbackToken ||
    ""
  ).trim();

  return {
    url: resolvedUrl.origin.replace(/\/+$/, ""),
    token,
  };
}

export function parseRemoteBridgeQrPayload(rawPayload: string): ParsedRemoteBridgeQr {
  const raw = rawPayload.trim();
  if (!raw) {
    throw new Error("未识别到二维码内容");
  }

  if (raw.startsWith("{")) {
    let parsedJson: Record<string, unknown>;
    try {
      parsedJson = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      throw new Error(INVALID_QR_ERROR);
    }
    if (!parsedJson || typeof parsedJson !== "object" || Array.isArray(parsedJson)) {
      throw new Error(INVALID_QR_ERROR);
    }
    const hostPortUrl =
      typeof parsedJson.host === "string" && parsedJson.host.trim() && parsedJson.port
        ? `http://${parsedJson.host.trim()}:${String(parsedJson.port).trim()}`
        : "";
    const candidateUrl = String(parsedJson.url || parsedJson.bridgeUrl || hostPortUrl || "").trim();
    if (!candidateUrl) {
      throw new Error(INVALID_QR_ERROR);
    }
    const candidateToken = String(parsedJson.token || parsedJson.bridgeToken || parsedJson.authToken || "").trim();
    return parseHttpUrlPayload(candidateUrl, candidateToken);
  }

  if (/^shinsekai:\/\//i.test(raw)) {
    let schemeUrl: URL;
    try {
      schemeUrl = new URL(raw);
    } catch {
      throw new Error(INVALID_QR_ERROR);
    }
    const targetUrl = (schemeUrl.searchParams.get("url") || schemeUrl.searchParams.get("bridge") || "").trim();
    if (!targetUrl) {
      throw new Error(INVALID_QR_ERROR);
    }
    const token = (
      schemeUrl.searchParams.get("shinsekai_bridge_token") ||
      schemeUrl.searchParams.get("token") ||
      ""
    ).trim();
    return parseHttpUrlPayload(targetUrl, token);
  }

  const candidate = normalizeHttpCandidate(raw);
  if (!/^https?:\/\//i.test(candidate)) {
    throw new Error(INVALID_QR_ERROR);
  }
  return parseHttpUrlPayload(candidate);
}

export function hasQrDecodeCapability(): boolean {
  return Boolean(typeof window !== "undefined" && (window.__SHINSEKAI_ANDROID_QR__ || window.BarcodeDetector));
}

async function getQrBarcodeDetector(): Promise<BarcodeDetectorInstance | null> {
  if (typeof window === "undefined" || !window.BarcodeDetector) {
    return null;
  }
  const ctor = window.BarcodeDetector;
  if (cachedDetectorCtor !== ctor) {
    cachedDetectorCtor = ctor;
    cachedDetector = null;
    detectorSupportPromise = null;
  }
  if (!detectorSupportPromise) {
    detectorSupportPromise = (async () => {
      try {
        if (typeof ctor.getSupportedFormats === "function") {
          const formats = await ctor.getSupportedFormats();
          return Array.isArray(formats) && formats.includes("qr_code");
        }
        return true;
      } catch {
        return false;
      }
    })();
  }
  const supported = await detectorSupportPromise;
  if (!supported) {
    return null;
  }
  if (!cachedDetector) {
    try {
      cachedDetector = new ctor({ formats: ["qr_code"] });
    } catch {
      return null;
    }
  }
  return cachedDetector;
}

export async function decodeQrFromCanvas(canvas: HTMLCanvasElement): Promise<string | null> {
  const detector = await getQrBarcodeDetector();
  if (detector) {
    try {
      const results = await detector.detect(canvas);
      const raw = results?.[0]?.rawValue?.trim();
      if (raw) {
        return raw;
      }
    } catch {
      // Fall back to Android native ZXing bridge when BarcodeDetector is unavailable
    }
  }

  const androidBridge = typeof window !== "undefined" ? window.__SHINSEKAI_ANDROID_QR__ : undefined;
  if (androidBridge?.decodeImageDataUrl) {
    try {
      const decoded = androidBridge.decodeImageDataUrl(canvas.toDataURL("image/jpeg", 0.86));
      if (typeof decoded === "string" && decoded.trim()) {
        return decoded.trim();
      }
    } catch {
      // Ignore native bridge decoding error and return null
    }
  }

  return null;
}

export async function decodeQrFromVideoFrame(
  video: HTMLVideoElement,
  workCanvas: HTMLCanvasElement,
): Promise<string | null> {
  if (video.readyState < 2 || video.videoWidth <= 0 || video.videoHeight <= 0) {
    return null;
  }
  const maxDim = Math.max(video.videoWidth, video.videoHeight);
  const scale = maxDim > 720 ? 720 / maxDim : 1;
  const targetWidth = Math.max(1, Math.round(video.videoWidth * scale));
  const targetHeight = Math.max(1, Math.round(video.videoHeight * scale));
  workCanvas.width = targetWidth;
  workCanvas.height = targetHeight;

  const ctx = workCanvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) {
    return null;
  }
  ctx.drawImage(video, 0, 0, targetWidth, targetHeight);
  return decodeQrFromCanvas(workCanvas);
}

function loadImageElement(objectUrl: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("无法读取所选图片"));
    img.src = objectUrl;
  });
}

export async function decodeQrFromImageFile(file: File): Promise<string | null> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const img = await loadImageElement(objectUrl);
    const naturalWidth = img.naturalWidth || img.width;
    const naturalHeight = img.naturalHeight || img.height;
    if (naturalWidth <= 0 || naturalHeight <= 0) {
      return null;
    }

    const canvas = document.createElement("canvas");
    const maxDim = Math.max(naturalWidth, naturalHeight);
    const scale = maxDim > 1280 ? 1280 / maxDim : 1;
    canvas.width = Math.max(1, Math.round(naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(naturalHeight * scale));

    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) {
      return null;
    }
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const fullResult = await decodeQrFromCanvas(canvas);
    if (fullResult) {
      return fullResult;
    }

    // Retry with a centered 70% crop in case the user uploaded a full-desktop screenshot
    const cropWidth = Math.max(1, Math.round(naturalWidth * 0.7));
    const cropHeight = Math.max(1, Math.round(naturalHeight * 0.7));
    const cropX = Math.round((naturalWidth - cropWidth) / 2);
    const cropY = Math.round((naturalHeight - cropHeight) / 2);
    const cropMaxDim = Math.max(cropWidth, cropHeight);
    const cropScale = cropMaxDim > 1080 ? 1080 / cropMaxDim : 1;
    canvas.width = Math.max(1, Math.round(cropWidth * cropScale));
    canvas.height = Math.max(1, Math.round(cropHeight * cropScale));
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, cropX, cropY, cropWidth, cropHeight, 0, 0, canvas.width, canvas.height);

    return decodeQrFromCanvas(canvas);
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
