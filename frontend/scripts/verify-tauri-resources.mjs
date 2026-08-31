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
await assertExists(path.join(resourcesDir, "application", "chat", "mobile_access.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "runtime_process.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "commands.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "manage_branches.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "startup.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "session_runtime.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "presentation.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "wire_streaming_session.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "effects.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "initial_sprite.py"));
await assertExists(path.join(resourcesDir, "application", "chat", "turn_wiring.py"));
await assertExists(path.join(resourcesDir, "frontend_bridge_core", "transport", "chat_session.py"));
await assertExists(path.join(resourcesDir, "application", "effects", "management.py"));
await assertExists(path.join(resourcesDir, "application", "runtime", "dependencies.py"));
await assertExists(path.join(resourcesDir, "frontend_bridge_core", "transport", "mobile_access.py"));
await assertExists(path.join(resourcesDir, "frontend_bridge_core", "transport", "chat_commands.py"));
await assertExists(path.join(resourcesDir, "ai", "llm", "llm_manager.py"));
await assertExists(path.join(resourcesDir, "ai", "asr", "asr_adapter.py"));
await assertExists(path.join(resourcesDir, "ai", "tts", "tts_manager.py"));
await assertExists(path.join(resourcesDir, "ai", "t2i", "t2i_manager.py"));
await assertExists(path.join(resourcesDir, "ai", "tools", "tool_manager.py"));
await assertExists(path.join(resourcesDir, "plugin_system", "host", "service.py"));
await assertExists(path.join(resourcesDir, "requirements-runtime-core.txt"));
await assertExists(path.join(resourcesDir, "assets", "system", "workflow", "default.yaml"));
await assertExists(path.join(resourcesDir, "assets", "system", "workflow", "headless.yaml"));
await assertExists(path.join(resourcesDir, "assets", "system", "picture", "shinsekai.png"));
await assertExists(path.join(resourcesDir, "assets", "system", "picture", "Icon.png"));
await assertExists(path.join(resourcesDir, "assets", "system", "picture", "dialog_frame.png"));
await assertExists(path.join(resourcesDir, "assets", "system", "sound", "switch.ogg"));
await assertExists(path.join(resourcesDir, "assets", "chat_ui_themes", "windborne-adventure", "theme.json"));
await assertExists(path.join(resourcesDir, "assets", "chat_ui_themes", "windborne-adventure", "preview.png"));
for (const retiredPath of [
  "ui",
  "llm",
  "asr",
  "tts",
  "t2i",
  path.join("core", "runtime"),
  path.join("core", "plugins"),
  path.join("core", "mobile_access"),
  path.join("core", "messaging", "chat_turn_wiring.py"),
  path.join("core", "sprite", "initial_sprite.py"),
  path.join("application", "media", "effects.py"),
  path.join("frontend_bridge_core", "handler.py"),
]) {
  await assertMissing(path.join(resourcesDir, retiredPath));
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

async function assertMissing(filePath) {
  try {
    await access(filePath);
  } catch {
    return;
  }
  throw new Error(`retired Tauri resource is still staged: ${path.relative(frontendDir, filePath)}`);
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
