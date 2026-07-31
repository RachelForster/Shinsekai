import { containsPathControlCharacter, isPortablePathComponent } from "../paths/pathContract";

export type MediaSourceKind = "empty" | "direct" | "local" | "unsupported";

const DIRECT_MEDIA_SCHEME = /^(?:https?:|blob:|data:|asset:)/i;
const URI_SCHEME = /^[a-z][a-z\d+.-]*:/i;
const WINDOWS_ABSOLUTE_PATH = /^[a-z]:[\\/]/i;

function hasAmbiguousUrlAuthority(value: string) {
  const marker = value.indexOf("//");
  if (marker < 0) {
    return true;
  }
  const tail = value.slice(marker + 2);
  const end = tail.search(/[/?#]/u);
  const authority = end < 0 ? tail : tail.slice(0, end);
  return !authority || /[%@\s\\]/u.test(authority);
}

function isSupportedDirectMediaUrl(value: string) {
  if (/^https?:/iu.test(value)) {
    if (value.includes("\\") || hasAmbiguousUrlAuthority(value)) {
      return false;
    }
    try {
      const parsed = new URL(value);
      return /^https?:$/u.test(parsed.protocol) && Boolean(parsed.hostname) && !parsed.username && !parsed.password;
    } catch {
      return false;
    }
  }
  if (/^blob:/iu.test(value)) {
    return value.slice("blob:".length).length > 0;
  }
  if (/^data:/iu.test(value)) {
    return value.indexOf(",", "data:".length) >= 0;
  }
  if (/^asset:/iu.test(value)) {
    if (value.includes("\\") || hasAmbiguousUrlAuthority(value)) {
      return false;
    }
    try {
      const parsed = new URL(value);
      return parsed.protocol === "asset:" && Boolean(parsed.hostname) && !parsed.username && !parsed.password;
    } catch {
      return false;
    }
  }
  return false;
}

function isExactApplicationAssetUrl(value: string) {
  const pathEnd = value.search(/[?#]/u);
  const encodedPath = pathEnd < 0 ? value : value.slice(0, pathEnd);
  if (/%(?:2f|5c)/iu.test(encodedPath)) {
    return false;
  }
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(encodedPath);
  } catch {
    return false;
  }
  if (!decodedPath.startsWith("/assets/") || decodedPath.includes("\\") || containsPathControlCharacter(decodedPath)) {
    return false;
  }
  const parts = decodedPath.slice(1).split("/");
  return parts.length > 1 && parts.every(isPortablePathComponent);
}

/**
 * Keep URL classification separate from host-path classification.
 *
 * A Windows absolute path starts with text that is syntactically a URI
 * scheme (`C:`).  Checking for a generic scheme first therefore makes React
 * hand `C:\...` directly to the webview instead of routing it through the
 * desktop media bridge.
 */
export function classifyMediaSource(value: string | null | undefined): MediaSourceKind {
  if (!value) {
    return "empty";
  }
  if (value !== value.trim() || containsPathControlCharacter(value)) {
    return "unsupported";
  }
  if (value.startsWith("/assets/")) {
    return isExactApplicationAssetUrl(value) ? "direct" : "unsupported";
  }
  if (DIRECT_MEDIA_SCHEME.test(value)) {
    return isSupportedDirectMediaUrl(value) ? "direct" : "unsupported";
  }
  if (WINDOWS_ABSOLUTE_PATH.test(value)) {
    return "local";
  }
  if (URI_SCHEME.test(value)) {
    return "unsupported";
  }
  return "local";
}

export function isDirectMediaSource(value: string | null | undefined) {
  return classifyMediaSource(value) === "direct";
}
