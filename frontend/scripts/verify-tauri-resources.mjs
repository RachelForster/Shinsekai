import { lstat, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertContainedDirectoryTree,
  assertRegularFileWithoutLinks,
  readRegularFileWithoutLinks,
  resolveAbsoluteEnvironmentPath,
  resolveExactRelativePath,
  sameFilesystemIdentity,
  sha256RegularFileWithoutLinks,
} from "./path-contract.mjs";
import { collectTauriResourceMappings, tauriResourceProvenanceFile } from "./tauri-resource-plan.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const resourcesDir = path.join(frontendDir, "src-tauri", "resources");
const runtimeSource = resolveAbsoluteEnvironmentPath("SHINSEKAI_TAURI_RUNTIME_DIR", path.join(repoRoot, "runtime"));
const runtimeMarkerPath = path.join(resourcesDir, "runtime", ".shinsekai-runtime.json");

assertContainedDirectoryTree(resourcesDir, "Tauri resource staging tree", {
  allowContainedSymbolicLinks: false,
});
const resourcesDirectoryIdentity = await lstat(resourcesDir, {
  bigint: true,
});
await verifyResourceProvenance();
const runtimeMarker = await readJson(runtimeMarkerPath);

if (runtimeMarker.provider && runtimeMarker.provider !== "python-build-standalone") {
  throw new Error(`unexpected embedded runtime provider: ${runtimeMarker.provider}`);
}
if (runtimeMarker.source !== "python-build-standalone") {
  throw new Error(`unexpected embedded runtime source: ${runtimeMarker.source}`);
}

const runtimeRoot = path.join(resourcesDir, "runtime");
await assertRegularFile(runtimePythonPath(runtimeRoot, runtimeMarker));
if (!Array.isArray(runtimeMarker.requiredFiles)) {
  throw new Error("embedded runtime marker requiredFiles must be an array");
}
for (const requiredFile of runtimeMarker.requiredFiles) {
  await assertRegularFile(resolveExactRelativePath(runtimeRoot, requiredFile, "embedded runtime required file"));
}
await assertRegularFile(path.join(resourcesDir, "runtime_manifest.json"));
await assertRegularFile(path.join(resourcesDir, "main.py"));
await assertRegularFile(path.join(resourcesDir, "frontend_bridge.py"));
await assertRegularFile(path.join(resourcesDir, "application", "chat", "mobile_access.py"));
await assertRegularFile(path.join(resourcesDir, "application", "chat", "runtime_process.py"));
await assertRegularFile(path.join(resourcesDir, "application", "runtime", "dependencies.py"));
await assertRegularFile(path.join(resourcesDir, "frontend_bridge_core", "transport", "mobile_access.py"));
await assertRegularFile(path.join(resourcesDir, "ai", "llm", "llm_manager.py"));
await assertRegularFile(path.join(resourcesDir, "ai", "asr", "asr_adapter.py"));
await assertRegularFile(path.join(resourcesDir, "ai", "tts", "tts_manager.py"));
await assertRegularFile(path.join(resourcesDir, "ai", "t2i", "t2i_manager.py"));
await assertRegularFile(path.join(resourcesDir, "ai", "tools", "tool_manager.py"));
await assertRegularFile(path.join(resourcesDir, "plugin_system", "host", "service.py"));
await assertRegularFile(path.join(resourcesDir, "requirements-runtime-core.txt"));
await assertRegularFile(path.join(resourcesDir, "assets", "system", "workflow", "default.yaml"));
await assertRegularFile(path.join(resourcesDir, "assets", "system", "workflow", "headless.yaml"));
await assertRegularFile(path.join(resourcesDir, "assets", "system", "picture", "shinsekai.png"));
await assertRegularFile(path.join(resourcesDir, "assets", "system", "picture", "Icon.png"));
await assertRegularFile(path.join(resourcesDir, "assets", "system", "picture", "dialog_frame.png"));
await assertRegularFile(path.join(resourcesDir, "assets", "system", "sound", "switch.ogg"));
await assertRegularFile(path.join(resourcesDir, "assets", "chat_ui_themes", "windborne-adventure", "theme.json"));
await assertRegularFile(path.join(resourcesDir, "assets", "chat_ui_themes", "windborne-adventure", "preview.png"));
for (const retiredPath of [
  "ui",
  "llm",
  "asr",
  "tts",
  "t2i",
  path.join("core", "runtime"),
  path.join("core", "plugins"),
  path.join("core", "mobile_access"),
  path.join("frontend_bridge_core", "handler.py"),
]) {
  await assertMissing(path.join(resourcesDir, retiredPath));
}
assertContainedDirectoryTree(resourcesDir, "Tauri resource staging tree", {
  allowContainedSymbolicLinks: false,
});
await requireDirectoryIdentity(resourcesDir, resourcesDirectoryIdentity, "Tauri resource staging tree");

console.log(`Verified Tauri resources for ${runtimeMarker.target} ${runtimeMarker.triple}`);

async function readJson(filePath) {
  try {
    return JSON.parse(
      (
        await readRegularFileWithoutLinks(filePath, {
          field: "Tauri resource JSON file",
          encoding: "utf8",
        })
      ).data,
    );
  } catch (error) {
    throw new Error(`failed to read ${path.relative(frontendDir, filePath)}: ${error.message}`);
  }
}

async function assertRegularFile(filePath) {
  try {
    assertRegularFileWithoutLinks(filePath, "required Tauri resource");
  } catch {
    throw new Error(`required Tauri resource is missing or unsafe: ${path.relative(frontendDir, filePath)}`);
  }
}

async function assertMissing(filePath) {
  try {
    await lstat(filePath);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return;
    }
    throw error;
  }
  throw new Error(`retired Tauri resource is still staged: ${path.relative(frontendDir, filePath)}`);
}

function runtimePythonPath(runtimeRoot, marker) {
  if (marker.target?.startsWith("windows-")) {
    return path.join(runtimeRoot, "python.exe");
  }
  const version = /^([0-9]+)\.([0-9]+)(?:\.[0-9]+)?$/u.exec(String(marker.python ?? ""));
  if (version) {
    return path.join(runtimeRoot, "bin", `python${version[1]}.${version[2]}`);
  }
  throw new Error(`embedded runtime marker has an invalid Python version: ${String(marker.python ?? "")}`);
}

async function verifyResourceProvenance() {
  const provenancePath = path.join(resourcesDir, tauriResourceProvenanceFile);
  const provenance = await readJson(provenancePath);
  if (provenance?.schema !== 1 || !Array.isArray(provenance.records)) {
    throw new Error("Tauri resource provenance has an unsupported schema");
  }

  const mappings = await collectTauriResourceMappings({
    frontendDir,
    repoRoot,
    runtimeSource,
  });
  if (provenance.records.length !== mappings.length) {
    throw new Error(
      `Tauri resources are stale: expected ${mappings.length} source files, provenance has ${provenance.records.length}`,
    );
  }

  for (let index = 0; index < mappings.length; index += 1) {
    const item = mappings[index];
    const record = provenance.records[index];
    if (
      record?.source !== item.source ||
      record?.destination !== item.destination ||
      !/^[a-f0-9]{64}$/u.test(String(record?.sha256 ?? ""))
    ) {
      throw new Error(`Tauri resource provenance differs from the source plan at record ${index}`);
    }
    const stagedPath = resolveExactRelativePath(resourcesDir, item.destination, "staged Tauri resource");
    const [sourceSha256, stagedSha256] = await Promise.all([
      sha256File(item.sourcePath, "Tauri resource source"),
      sha256File(stagedPath, "staged Tauri resource"),
    ]);
    if (sourceSha256 !== record.sha256 || stagedSha256 !== record.sha256) {
      throw new Error(`Tauri resource is stale or changed: ${item.destination}`);
    }
  }

  const actualFiles = await collectStagedFiles(resourcesDir);
  const expectedFiles = [".gitkeep", tauriResourceProvenanceFile, ...mappings.map((item) => item.destination)].sort();
  if (JSON.stringify(actualFiles) !== JSON.stringify(expectedFiles)) {
    throw new Error("Tauri resource staging tree contains missing or unplanned files");
  }
  const currentMappings = await collectTauriResourceMappings({
    frontendDir,
    repoRoot,
    runtimeSource,
  });
  if (JSON.stringify(mappingKeys(currentMappings)) !== JSON.stringify(mappingKeys(mappings))) {
    throw new Error("Tauri resource source set changed during verification");
  }
}

async function collectStagedFiles(root) {
  const files = [];
  const visit = async (directory, relativeDirectory) => {
    const directoryIdentity = await lstat(directory, { bigint: true });
    if (!directoryIdentity.isDirectory() || directoryIdentity.isSymbolicLink()) {
      throw new Error(`Tauri resource staging path is not a stable directory: ${directory}`);
    }
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const relativePath = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name;
      const entryPath = resolveExactRelativePath(directory, entry.name, "staged Tauri resource entry");
      const entryIdentity = await lstat(entryPath, { bigint: true });
      if (entryIdentity.isSymbolicLink()) {
        throw new Error(`Tauri resource staging tree contains a symbolic link: ${relativePath}`);
      }
      if (entryIdentity.isDirectory()) {
        await visit(entryPath, relativePath);
      } else if (entryIdentity.isFile()) {
        files.push(relativePath.split(path.sep).join("/"));
      } else {
        throw new Error(`Tauri resource staging tree contains an unsupported entry: ${relativePath}`);
      }
    }
    const currentDirectoryIdentity = await lstat(directory, { bigint: true });
    if (!sameStableDirectoryState(directoryIdentity, currentDirectoryIdentity)) {
      throw new Error(`Tauri resource staging directory changed during enumeration: ${directory}`);
    }
  };
  await visit(root, "");
  return files.sort();
}

function sameStableDirectoryState(left, right) {
  return (
    left.isDirectory() &&
    !left.isSymbolicLink() &&
    right.isDirectory() &&
    !right.isSymbolicLink() &&
    sameFilesystemIdentity(left, right) &&
    left.mode === right.mode &&
    left.size === right.size &&
    left.mtimeNs === right.mtimeNs &&
    left.ctimeNs === right.ctimeNs
  );
}

async function sha256File(filePath, field) {
  return (
    await sha256RegularFileWithoutLinks(filePath, {
      field,
    })
  ).sha256;
}

function mappingKeys(mappings) {
  return mappings.map((item) => [path.resolve(item.sourcePath), item.source, item.destination]);
}

async function requireDirectoryIdentity(target, expectedIdentity, field) {
  const currentIdentity = await lstat(target, { bigint: true });
  if (
    !currentIdentity.isDirectory() ||
    currentIdentity.isSymbolicLink() ||
    !sameFilesystemIdentity(expectedIdentity, currentIdentity)
  ) {
    throw new Error(`${field} identity changed`);
  }
}
