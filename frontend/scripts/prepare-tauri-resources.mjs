import { access, cp, mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const stageRoot = path.join(frontendDir, "src-tauri", "resources");
const runtimeEnv = process.env.SHINSEKAI_TAURI_RUNTIME_DIR?.trim();
const runtimeSource = runtimeEnv ? path.resolve(runtimeEnv) : path.join(repoRoot, "runtime");

const files = [
  "VERSION",
  "frontend_bridge.py",
  "requirements.txt",
  "requirements-runtime-core.txt",
  "requirements-runtime-local-ai.txt",
  "requirements-dev.txt",
];
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

async function pathExists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
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
await writeFile(path.join(stageRoot, ".gitkeep"), "");

for (const file of files) {
  await copyFileToStage(file);
}

const runtimeManifest = path.join(frontendDir, "src-tauri", "runtime_manifest.json");
if (await pathExists(runtimeManifest)) {
  await cp(runtimeManifest, path.join(stageRoot, "runtime_manifest.json"), { force: true });
}

for (const directory of directories) {
  await copyDirectoryToStage(directory);
}

await cp(path.join(frontendDir, "dist"), path.join(stageRoot, "frontend", "dist"), {
  errorOnExist: false,
  force: true,
  recursive: true,
});

if (await pathExists(runtimeSource)) {
  await cp(runtimeSource, path.join(stageRoot, "runtime"), {
    dereference: true,
    errorOnExist: false,
    filter,
    force: true,
    recursive: true,
  });
  console.log(`Prepared embedded Python runtime from ${path.relative(repoRoot, runtimeSource) || "."}`);
} else if (runtimeEnv) {
  throw new Error(`SHINSEKAI_TAURI_RUNTIME_DIR does not exist: ${runtimeSource}`);
} else {
  console.log("No embedded Python runtime found; packaged app will use configured or system Python.");
}

console.log("Runtime dependency repair will use configured pip indexes.");

console.log(`Prepared Tauri resources in ${path.relative(repoRoot, stageRoot)}`);
