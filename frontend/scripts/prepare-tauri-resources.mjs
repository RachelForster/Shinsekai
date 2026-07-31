import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, mkdtemp, open, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertContainedDirectoryTree,
  assertNonOverlappingDirectories,
  assertRegularFileWithoutLinks,
  assertSafeMutableDirectory,
  portableTemporaryPathPrefix,
  removeDirectoryWithoutLinks,
  replaceDirectoryTransactionally,
  resolveAbsoluteEnvironmentPath,
  resolveExactRelativePath,
  sameFilesystemIdentity,
} from "./path-contract.mjs";
import { collectTauriResourceMappings, tauriResourceProvenanceFile } from "./tauri-resource-plan.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const defaultStageRoot = path.join(frontendDir, "src-tauri", "resources");
const stageRoot = assertSafeMutableDirectory(defaultStageRoot, {
  field: "Tauri resource staging directory",
  protectedRoots: [repoRoot],
  allowedRoots: [defaultStageRoot],
});
const runtimeEnvIsSet = Object.prototype.hasOwnProperty.call(process.env, "SHINSEKAI_TAURI_RUNTIME_DIR");
const runtimeSource = resolveAbsoluteEnvironmentPath("SHINSEKAI_TAURI_RUNTIME_DIR", path.join(repoRoot, "runtime"));
assertNonOverlappingDirectories([
  { field: "Tauri resource staging directory", path: stageRoot },
  { field: "embedded runtime source", path: runtimeSource },
]);
if (runtimeEnvIsSet && !(await pathExists(runtimeSource))) {
  throw new Error(`SHINSEKAI_TAURI_RUNTIME_DIR does not exist: ${runtimeSource}`);
}
const resourceMappings = await collectTauriResourceMappings({
  frontendDir,
  repoRoot,
  runtimeSource,
});
const resourceSnapshots = await snapshotResourceMappings(resourceMappings);

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

async function directoryIdentityIfExists(target, field) {
  try {
    const metadata = await lstat(target, { bigint: true });
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new Error(`${field} must be a regular non-link directory`);
    }
    return metadata;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

const existingStageRootIdentity = await directoryIdentityIfExists(stageRoot, "Tauri resource destination");
const stageRootParentIdentity = await lstat(path.dirname(stageRoot), {
  bigint: true,
});
const stagingRoot = await mkdtemp(
  portableTemporaryPathPrefix(`${stageRoot}.tmp-`, {
    field: "Tauri resource staging temporary prefix",
  }),
);
const stagingRootIdentity = await lstat(stagingRoot, { bigint: true });
try {
  await writeFile(path.join(stagingRoot, ".gitkeep"), "");

  for (const item of resourceSnapshots) {
    await copyResourceSnapshot(stagingRoot, item);
  }
  if (await pathExists(runtimeSource)) {
    console.log(`Prepared embedded Python runtime from ${path.relative(repoRoot, runtimeSource) || "."}`);
  } else {
    console.log("No embedded Python runtime found; packaged app will use configured or system Python.");
  }

  await writeResourceProvenance(stagingRoot, resourceSnapshots);
  assertContainedDirectoryTree(stagingRoot, "prepared Tauri resource staging tree", {
    allowContainedSymbolicLinks: false,
  });
  await replaceDirectoryTransactionally(stagingRoot, stageRoot, {
    expectedDestinationIdentity: existingStageRootIdentity,
    expectedParentIdentity: stageRootParentIdentity,
    expectedStagingIdentity: stagingRootIdentity,
    field: "Tauri resource staging tree",
  });
} finally {
  await removeDirectoryWithoutLinks(stagingRoot, {
    expectedIdentity: stagingRootIdentity,
    expectedParentIdentity: stageRootParentIdentity,
    field: "temporary Tauri resource staging tree",
    missingOk: true,
  });
}

console.log("Runtime dependency repair will use configured pip indexes.");
console.log(`Prepared Tauri resources in ${path.relative(repoRoot, stageRoot)}`);

async function snapshotResourceMappings(mappings) {
  const snapshots = [];
  for (const item of mappings) {
    const snapshot = await readFileSnapshot(item.sourcePath, `Tauri resource source ${item.source}`);
    snapshots.push({ ...item, ...snapshot });
  }
  return snapshots;
}

async function copyResourceSnapshot(stagingRoot, item) {
  const destination = resolveExactRelativePath(stagingRoot, item.destination, "staged Tauri resource");
  await mkdir(path.dirname(destination), { recursive: true });
  const source = assertRegularFileWithoutLinks(item.sourcePath, `Tauri resource source ${item.source}`);
  await assertParentIdentity(source, item.parentIdentity, `Tauri resource source ${item.source}`);

  const sourceHandle = await open(source, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  let destinationHandle = null;
  try {
    await assertOpenFileIdentity(source, sourceHandle, item.identity, `Tauri resource source ${item.source}`);
    destinationHandle = await open(destination, "wx", 0o600);
    const hash = createHash("sha256");
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let position = 0;
    while (true) {
      const { bytesRead } = await sourceHandle.read(buffer, 0, buffer.length, position);
      if (bytesRead === 0) {
        break;
      }
      hash.update(buffer.subarray(0, bytesRead));
      let written = 0;
      while (written < bytesRead) {
        const result = await destinationHandle.write(buffer, written, bytesRead - written, position + written);
        if (result.bytesWritten <= 0) {
          throw new Error(`staged Tauri resource write made no progress: ${item.destination}`);
        }
        written += result.bytesWritten;
      }
      position += bytesRead;
    }
    if (hash.digest("hex") !== item.sha256) {
      throw new Error(`Tauri resource source changed while copying ${item.source}`);
    }
    await destinationHandle.chmod(Number(item.identity.mode & 0o777n));
    await destinationHandle.sync();
    await assertOpenFileIdentity(source, sourceHandle, item.identity, `Tauri resource source ${item.source}`);
    await assertParentIdentity(source, item.parentIdentity, `Tauri resource source ${item.source}`);
  } finally {
    await destinationHandle?.close();
    await sourceHandle.close();
  }
  const stagedSnapshot = await readFileSnapshot(destination, `staged Tauri resource ${item.destination}`);
  if (stagedSnapshot.sha256 !== item.sha256) {
    throw new Error(`Tauri resource copy changed content for ${item.source}`);
  }
}

async function writeResourceProvenance(stagingRoot, mappings) {
  const currentMappings = await collectTauriResourceMappings({
    frontendDir,
    repoRoot,
    runtimeSource,
  });
  assertResourcePlanUnchanged(mappings, currentMappings);

  const records = [];
  for (const item of mappings) {
    const stagedPath = resolveExactRelativePath(stagingRoot, item.destination, "staged Tauri resource");
    const [sourceSnapshot, stagedSnapshot] = await Promise.all([
      readFileSnapshot(item.sourcePath, `Tauri resource source ${item.source}`, {
        expectedIdentity: item.identity,
        expectedParentIdentity: item.parentIdentity,
        expectedSha256: item.sha256,
      }),
      readFileSnapshot(stagedPath, `staged Tauri resource ${item.destination}`, {
        expectedSha256: item.sha256,
      }),
    ]);
    if (sourceSnapshot.sha256 !== stagedSnapshot.sha256) {
      throw new Error(`Tauri resource copy changed content for ${item.source}`);
    }
    records.push({
      source: item.source,
      destination: item.destination,
      sha256: item.sha256,
    });
  }
  await writeFile(
    path.join(stagingRoot, tauriResourceProvenanceFile),
    `${JSON.stringify({ schema: 1, records }, null, 2)}\n`,
  );
}

function assertResourcePlanUnchanged(expectedSnapshots, currentMappings) {
  if (expectedSnapshots.length !== currentMappings.length) {
    throw new Error("Tauri resource source set changed while staging");
  }
  for (let index = 0; index < expectedSnapshots.length; index += 1) {
    const expected = expectedSnapshots[index];
    const current = currentMappings[index];
    if (
      expected.source !== current.source ||
      expected.destination !== current.destination ||
      path.resolve(expected.sourcePath) !== path.resolve(current.sourcePath)
    ) {
      throw new Error("Tauri resource source set changed while staging");
    }
  }
}

async function readFileSnapshot(
  filePath,
  field,
  { expectedIdentity = null, expectedParentIdentity = null, expectedSha256 = null } = {},
) {
  const source = assertRegularFileWithoutLinks(filePath, field);
  const parentIdentity = await lstat(path.dirname(source), { bigint: true });
  if (!parentIdentity.isDirectory() || parentIdentity.isSymbolicLink()) {
    throw new Error(`${field} parent must be a regular non-link directory`);
  }
  if (expectedParentIdentity !== null && !sameFilesystemIdentity(expectedParentIdentity, parentIdentity)) {
    throw new Error(`${field} parent identity changed`);
  }
  const handle = await open(source, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const identity = await handle.stat({ bigint: true });
    if (!identity.isFile() || identity.isSymbolicLink()) {
      throw new Error(`${field} must be a regular non-link file`);
    }
    if (expectedIdentity !== null && !sameStableFileIdentity(expectedIdentity, identity)) {
      throw new Error(`${field} identity changed`);
    }
    await assertOpenFileIdentity(source, handle, identity, field);
    await assertParentIdentity(source, parentIdentity, field);
    const hash = createHash("sha256");
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let position = 0;
    while (true) {
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
      if (bytesRead === 0) {
        break;
      }
      hash.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    await assertOpenFileIdentity(source, handle, identity, field);
    await assertParentIdentity(source, parentIdentity, field);
    const sha256 = hash.digest("hex");
    if (expectedSha256 !== null && sha256 !== expectedSha256) {
      throw new Error(`${field} content changed`);
    }
    return { identity, parentIdentity, sha256 };
  } finally {
    await handle.close();
  }
}

async function assertOpenFileIdentity(filePath, handle, expectedIdentity, field) {
  assertRegularFileWithoutLinks(filePath, field);
  const [openedIdentity, currentIdentity] = await Promise.all([
    handle.stat({ bigint: true }),
    lstat(filePath, { bigint: true }),
  ]);
  if (
    !openedIdentity.isFile() ||
    openedIdentity.isSymbolicLink() ||
    !currentIdentity.isFile() ||
    currentIdentity.isSymbolicLink() ||
    !sameStableFileIdentity(expectedIdentity, openedIdentity) ||
    !sameStableFileIdentity(expectedIdentity, currentIdentity)
  ) {
    throw new Error(`${field} identity changed`);
  }
}

async function assertParentIdentity(filePath, expectedIdentity, field) {
  const currentIdentity = await lstat(path.dirname(filePath), { bigint: true });
  if (
    !currentIdentity.isDirectory() ||
    currentIdentity.isSymbolicLink() ||
    !sameFilesystemIdentity(expectedIdentity, currentIdentity)
  ) {
    throw new Error(`${field} parent identity changed`);
  }
}

function sameStableFileIdentity(left, right) {
  return (
    sameFilesystemIdentity(left, right) &&
    left.mode === right.mode &&
    left.size === right.size &&
    left.mtimeNs === right.mtimeNs &&
    left.ctimeNs === right.ctimeNs
  );
}
