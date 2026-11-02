/** Keep canvas pixel density bounded without changing the surface's aspect ratio. */
export function avatarRenderSize(width: number, height: number, devicePixelRatio: number) {
  const ratio = Math.min(2, devicePixelRatio || 1, 4096 / Math.max(1, width, height));
  return {
    width: Math.max(1, Math.round(width * ratio)),
    height: Math.max(1, Math.round(height * ratio)),
  };
}
