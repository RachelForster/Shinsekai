export const VISUAL_MEDIA_EXTENSIONS = [".gif", ".jpeg", ".jpg", ".png", ".webp", ".mp4", ".webm"];

/** Bridge URLs put the original filename in `path`, before any access token. */
export function isMp4Media(source: string): boolean {
  if (/^(?:data:|blob:)/i.test(source)) return /^data:video\/mp4[;,]/i.test(source);
  try {
    const url = new URL(source.replaceAll("\\", "/"), "http://localhost");
    return /\.mp4$/i.test(url.pathname) || /\.mp4$/i.test(url.searchParams.get("path") ?? "");
  } catch {
    return /\.mp4(?:[?#]|$)/i.test(source);
  }
}

export function isVideoMedia(source: string): boolean {
  if (isMp4Media(source)) return true;
  if (/^(?:data:|blob:)/i.test(source)) return /^data:video\/webm[;,]/i.test(source);
  try {
    const url = new URL(source.replaceAll("\\", "/"), "http://localhost");
    return /\.webm$/i.test(url.pathname) || /\.webm$/i.test(url.searchParams.get("path") ?? "");
  } catch {
    return /\.webm(?:[?#]|$)/i.test(source);
  }
}
