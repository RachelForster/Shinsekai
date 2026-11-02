/** Resolve package dependencies without leaving the model directory or losing bridge auth. */
export function avatarAssetUrl(modelUrl: string, relativePath: string): string {
  const path = decodeURIComponent(relativePath).replaceAll("\\", "/");
  if (!path || path.startsWith("/") || /[:?#\x00-\x1f]/.test(path) || path.split("/").includes("..")) {
    throw new Error("Avatar dependency must stay inside the model directory");
  }
  const model = new URL(modelUrl, window.location.href);
  if (!/^https?:$/.test(model.protocol)) throw new Error("Unsupported avatar model URL");
  const mediaPath = model.searchParams.get("path");
  if (model.pathname === "/api/avatar/file") {
    model.searchParams.set("path", path);
    return model.toString();
  }
  if (model.pathname === "/api/media" && mediaPath) {
    const normalized = mediaPath.replaceAll("\\", "/");
    model.searchParams.set("path", normalized.slice(0, normalized.lastIndexOf("/") + 1) + path);
    return model.toString();
  }
  model.pathname =
    model.pathname.slice(0, model.pathname.lastIndexOf("/") + 1) + path.split("/").map(encodeURIComponent).join("/");
  return model.toString();
}

/** The bridge owns writable runtimes; preserve its origin and access token in desktop/mobile hosts. */
export function avatarRuntimeAssetUrl(modelUrl: string, format: string, filename: string): string {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(format) || !/^[a-zA-Z0-9_.-]+$/.test(filename) || filename.includes("..")) {
    throw new Error("Invalid avatar runtime resource");
  }
  const url = new URL(modelUrl, window.location.href);
  if (!/^https?:$/.test(url.protocol)) throw new Error("Unsupported avatar model URL");
  url.pathname = "/api/avatar/runtime/file";
  url.hash = "";
  url.searchParams.delete("model_path");
  url.searchParams.set("format", format);
  url.searchParams.set("path", filename);
  return url.toString();
}
