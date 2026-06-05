import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const resourcesDir = path.join(frontendDir, "src-tauri", "resources");
const runtimeMarkerPath = path.join(resourcesDir, "runtime", ".shinsekai-runtime.json");

const runtimeMarker = await readJson(runtimeMarkerPath);

if (runtimeMarker.provider && runtimeMarker.provider !== "python-build-standalone") {
  throw new Error(`unexpected embedded runtime provider: ${runtimeMarker.provider}`);
}
if (runtimeMarker.source !== "python-build-standalone") {
  throw new Error(`unexpected embedded runtime source: ${runtimeMarker.source}`);
}

await assertExists(runtimePythonPath(runtimeMarker));
for (const requiredFile of runtimeMarker.requiredFiles ?? []) {
  await assertExists(path.join(resourcesDir, "runtime", requiredFile));
}
await assertExists(path.join(resourcesDir, "runtime_manifest.json"));
await assertExists(path.join(resourcesDir, "main.py"));
await assertExists(path.join(resourcesDir, "frontend_bridge.py"));
await assertExists(path.join(resourcesDir, "requirements-runtime-core.txt"));
await assertExists(path.join(resourcesDir, "assets", "system", "workflow", "default.yaml"));
await assertExists(path.join(resourcesDir, "assets", "system", "workflow", "headless.yaml"));
await assertExists(path.join(resourcesDir, "assets", "system", "picture", "shinsekai.png"));
await assertExists(path.join(resourcesDir, "assets", "system", "picture", "Icon.png"));
await assertExists(path.join(resourcesDir, "assets", "system", "picture", "dialog_frame.png"));
await assertExists(path.join(resourcesDir, "assets", "system", "sound", "switch.ogg"));

console.log(`Verified Tauri resources for ${runtimeMarker.target} ${runtimeMarker.triple}`);

async function readJson(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    throw new Error(`failed to read ${path.relative(frontendDir, filePath)}: ${error.message}`);
  }
}

async function assertExists(filePath) {
  try {
    await access(filePath);
  } catch {
    throw new Error(`required Tauri resource is missing: ${path.relative(frontendDir, filePath)}`);
  }
}

function runtimePythonPath(marker) {
  const runtimeRoot = path.join(resourcesDir, "runtime");
  if (marker.target?.startsWith("windows-")) {
    return path.join(runtimeRoot, "python.exe");
  }
  const [major, minor] = String(marker.python ?? "").split(".");
  if (major && minor) {
    return path.join(runtimeRoot, "bin", `python${major}.${minor}`);
  }
  return path.join(runtimeRoot, "bin", "python3");
}
