/** Resolve package dependencies without leaving the model directory or losing bridge auth. */
export function avatarAssetUrl(modelUrl: string, relativePath: string): string {
  const path = decodeURIComponent(relativePath).replaceAll("\\", "/");
  if (!path || path.startsWith("/") || /[:?#\x00-\x1f]/.test(path) || path.split("/").includes("..")) {
    throw new Error("Avatar dependency must stay inside the model directory");
  }
  const model = new URL(modelUrl, window.location.href);
  if (!/^https?:$/.test(model.protocol)) throw new Error("Unsupported avatar model URL");
  const mediaPath = model.searchParams.get("path");
  if (model.pathname === "/api/media" && mediaPath) {
    const normalized = mediaPath.replaceAll("\\", "/");
    model.searchParams.set("path", normalized.slice(0, normalized.lastIndexOf("/") + 1) + path);
    return model.toString();
  }
  model.pathname =
    model.pathname.slice(0, model.pathname.lastIndexOf("/") + 1) + path.split("/").map(encodeURIComponent).join("/");
  return model.toString();
}
