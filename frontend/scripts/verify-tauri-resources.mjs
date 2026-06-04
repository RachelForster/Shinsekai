import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const resourcesDir = path.join(frontendDir, "src-tauri", "resources");
const runtimeMarkerPath = path.join(resourcesDir, "runtime", ".shinsekai-runtime.json");
const wheelsMarkerPath = path.join(resourcesDir, "wheels", ".shinsekai-wheels.json");

const runtimeMarker = await readJson(runtimeMarkerPath);
const wheelsMarker = await readJson(wheelsMarkerPath);

if (runtimeMarker.provider && runtimeMarker.provider !== "python-build-standalone") {
  throw new Error(`unexpected embedded runtime provider: ${runtimeMarker.provider}`);
}
if (runtimeMarker.source !== "python-build-standalone") {
  throw new Error(`unexpected embedded runtime source: ${runtimeMarker.source}`);
}
if (wheelsMarker.provider !== "python-build-standalone") {
  throw new Error(`unexpected wheelhouse provider: ${wheelsMarker.provider}`);
}
if (runtimeMarker.target !== wheelsMarker.target) {
  throw new Error(`runtime target ${runtimeMarker.target} does not match wheelhouse target ${wheelsMarker.target}`);
}
if (runtimeMarker.triple !== wheelsMarker.triple) {
  throw new Error(`runtime triple ${runtimeMarker.triple} does not match wheelhouse triple ${wheelsMarker.triple}`);
}

await assertExists(runtimePythonPath(runtimeMarker));
for (const requiredFile of runtimeMarker.requiredFiles ?? []) {
  await assertExists(path.join(resourcesDir, "runtime", requiredFile));
}
await assertExists(path.join(resourcesDir, "wheels", "get-pip.py"));
for (const requirement of wheelsMarker.requirements ?? []) {
  const requirementName = path.basename(requirement);
  await assertExists(path.join(resourcesDir, requirementName));
}

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
