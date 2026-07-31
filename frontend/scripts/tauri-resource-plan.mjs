import { lstat, readdir } from "node:fs/promises";
import path from "node:path";

import {
  assertContainedDirectoryTree,
  assertRegularFileWithoutLinks,
  resolveExactRelativePath,
  sameFilesystemIdentity,
} from "./path-contract.mjs";

export const tauriResourceProvenanceFile = ".shinsekai-resource-sources.json";

export const tauriResourceFiles = [
  "VERSION",
  "main.py",
  "frontend_bridge.py",
  "requirements.txt",
  "requirements-runtime-core.txt",
  "requirements-runtime-local-ai.txt",
  "requirements-dev.txt",
];

export const tauriResourceDirectories = [
  "ai",
  "application",
  "assets",
  "config",
  "core",
  "frontend_bridge_core",
  "i18n",
  "live",
  "plugin_system",
  "sdk",
  "tools",
];

export function includeTauriResource(source) {
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

export async function collectTauriResourceMappings({ frontendDir, repoRoot, runtimeSource }) {
  const mappings = [];

  for (const relativePath of tauriResourceFiles) {
    const sourcePath = assertRegularFileWithoutLinks(
      path.join(repoRoot, relativePath),
      `Tauri resource source ${relativePath}`,
    );
    mappings.push(mapping(sourcePath, relativePath, relativePath));
  }

  const runtimeManifest = path.join(frontendDir, "src-tauri", "runtime_manifest.json");
  if (await pathExists(runtimeManifest)) {
    mappings.push(
      mapping(
        assertRegularFileWithoutLinks(runtimeManifest, "Tauri runtime manifest source"),
        "frontend/src-tauri/runtime_manifest.json",
        "runtime_manifest.json",
      ),
    );
  }

  for (const relativePath of tauriResourceDirectories) {
    await collectDirectoryMappings({
      mappings,
      sourceRoot: path.join(repoRoot, relativePath),
      sourcePrefix: relativePath,
      destinationPrefix: relativePath,
    });
  }

  await collectDirectoryMappings({
    mappings,
    sourceRoot: path.join(frontendDir, "dist"),
    sourcePrefix: "frontend/dist",
    destinationPrefix: "frontend/dist",
  });

  if (await pathExists(runtimeSource)) {
    await collectDirectoryMappings({
      mappings,
      sourceRoot: runtimeSource,
      sourcePrefix: "runtime",
      destinationPrefix: "runtime",
    });
  }

  mappings.sort(
    (left, right) => left.destination.localeCompare(right.destination) || left.source.localeCompare(right.source),
  );
  const destinations = new Set();
  for (const item of mappings) {
    if (destinations.has(item.destination)) {
      throw new Error(`Tauri resource plan has duplicate destination ${item.destination}`);
    }
    destinations.add(item.destination);
  }
  return mappings;
}

async function collectDirectoryMappings({ mappings, sourceRoot, sourcePrefix, destinationPrefix }) {
  assertContainedDirectoryTree(sourceRoot, `Tauri resource source ${sourcePrefix}`, {
    allowContainedSymbolicLinks: false,
  });

  const visit = async (directory, relativeDirectory) => {
    const directoryIdentity = await lstat(directory, { bigint: true });
    if (!directoryIdentity.isDirectory() || directoryIdentity.isSymbolicLink()) {
      throw new Error(`Tauri resource source is not a stable directory: ${directory}`);
    }
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const entryPath = resolveExactRelativePath(directory, entry.name, "Tauri resource source entry");
      if (!includeTauriResource(entryPath)) {
        continue;
      }
      const entryIdentity = await lstat(entryPath, { bigint: true });
      if (entryIdentity.isSymbolicLink()) {
        throw new Error(`Tauri resource source contains a symbolic link: ${entryPath}`);
      }
      const relativePath = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name;
      if (entryIdentity.isDirectory()) {
        await visit(entryPath, relativePath);
      } else if (entryIdentity.isFile()) {
        mappings.push(
          mapping(
            entryPath,
            toPosix(path.join(sourcePrefix, relativePath)),
            toPosix(path.join(destinationPrefix, relativePath)),
          ),
        );
      } else {
        throw new Error(`Tauri resource source contains an unsupported entry: ${entryPath}`);
      }
    }
    const currentDirectoryIdentity = await lstat(directory, { bigint: true });
    if (!sameStableDirectoryState(directoryIdentity, currentDirectoryIdentity)) {
      throw new Error(`Tauri resource source directory changed during enumeration: ${directory}`);
    }
  };

  await visit(sourceRoot, "");
  assertContainedDirectoryTree(sourceRoot, `Tauri resource source ${sourcePrefix}`, {
    allowContainedSymbolicLinks: false,
  });
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

function mapping(sourcePath, source, destination) {
  return {
    sourcePath,
    source: toPosix(source),
    destination: toPosix(destination),
  };
}

async function pathExists(target) {
  try {
    await lstat(target);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

function toPosix(value) {
  return value.split(path.sep).join("/");
}
