import { portraitGeometry } from "../../../shared/components/Portrait";
import type { PortraitCrop } from "../../../shared/platform/types";
export function cropGraphAvatar(source: CanvasImageSource, width: number, height: number, crop: PortraitCrop) {
  if (!width || !height) return undefined;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const context = canvas.getContext("2d");
    if (!context) return undefined;
    const { left, top, side } = portraitGeometry(width, height, crop);
    context.drawImage(source, left, top, side, side, 0, 0, 128, 128);
    return canvas;
  } catch {
    return undefined;
  }
}

export function prepareGraphAvatar(
  url: string,
  isVideoSource: boolean,
  crop: PortraitCrop,
  signal: AbortSignal,
): Promise<HTMLCanvasElement | undefined> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(undefined);
      return;
    }
    const media = isVideoSource ? document.createElement("video") : document.createElement("img");
    media.crossOrigin = "anonymous";
    const abort = () => finish();
    signal.addEventListener("abort", abort, { once: true });
    media.onerror = () => finish();
    if (media instanceof HTMLVideoElement) {
      media.muted = true;
      media.preload = "auto";
      media.onloadeddata = () => finish(cropGraphAvatar(media, media.videoWidth, media.videoHeight, crop));
    } else if (media instanceof HTMLImageElement) {
      media.onload = () => finish(cropGraphAvatar(media, media.naturalWidth, media.naturalHeight, crop));
    }
    media.src = url;

    function finish(result?: HTMLCanvasElement) {
      signal.removeEventListener("abort", abort);
      media.onload = null;
      media.onerror = null;
      if (media instanceof HTMLVideoElement) {
        media.onloadeddata = null;
        media.pause();
        media.removeAttribute("src");
        media.load();
      }
      resolve(result);
    }
  });
}
