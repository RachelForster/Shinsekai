import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const stageRoot = path.join(frontendDir, "src-tauri", "resources");

const files = ["VERSION", "frontend_bridge.py", "requirements.txt"];
const directories = [
  "assets",
  "asr",
  "config",
  "core",
  "frontend_bridge_core",
  "i18n",
  "live",
  "llm",
  "sdk",
  "t2i",
  "tools",
  "tts",
  "ui",
];

function filter(source) {
  const name = path.basename(source);
  if (name === "__pycache__") {
    return false;
  }
  if (name.endsWith(".pyc") || name.endsWith(".pyo")) {
    return false;
  }
  if (name === ".DS_Store") {
    return false;
  }
  return true;
}

async function copyFileToStage(relativePath) {
  await cp(path.join(repoRoot, relativePath), path.join(stageRoot, relativePath), { force: true });
}

async function copyDirectoryToStage(relativePath) {
  await cp(path.join(repoRoot, relativePath), path.join(stageRoot, relativePath), {
    errorOnExist: false,
    filter,
    force: true,
    recursive: true,
  });
}

await rm(stageRoot, { force: true, recursive: true });
await mkdir(stageRoot, { recursive: true });

for (const file of files) {
  await copyFileToStage(file);
}

for (const directory of directories) {
  await copyDirectoryToStage(directory);
}

await cp(path.join(frontendDir, "dist"), path.join(stageRoot, "frontend", "dist"), {
  errorOnExist: false,
  force: true,
  recursive: true,
});

console.log(`Prepared Tauri resources in ${path.relative(repoRoot, stageRoot)}`);
