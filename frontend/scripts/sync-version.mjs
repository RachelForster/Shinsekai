import { randomUUID } from "node:crypto";
import { lstat, open } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertRegularFileWithoutLinks,
  portableSiblingPath,
  readRegularFileWithoutLinks,
  removeFileWithoutLinks,
  replaceFileTransactionally,
  sameFilesystemIdentity,
} from "./path-contract.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const versionPath = path.join(repoRoot, "VERSION");

const version = (await readTextFile(versionPath, "VERSION file")).text.trim();
if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(version)) {
  throw new Error(`Invalid VERSION value: ${JSON.stringify(version)}`);
}

const changes = [];

await updateJsonVersion(path.join(frontendDir, "package.json"), version);
await updateJsonVersion(path.join(frontendDir, "src-tauri", "runtime_manifest.json"), version);
await updateTomlPackageVersion(path.join(frontendDir, "src-tauri", "Cargo.toml"), "shinsekai-desktop", version);
await updateCargoLockPackageVersion(path.join(frontendDir, "src-tauri", "Cargo.lock"), "shinsekai-desktop", version);
await updateOptionalTextFile(path.join(frontendDir, "src-tauri", "resources", "VERSION"), `${version}\n`);

if (changes.length === 0) {
  console.log(`All version files already match ${version}.`);
} else {
  console.log(`Synced version ${version}:`);
  for (const filePath of changes) {
    console.log(`- ${path.relative(repoRoot, filePath)}`);
  }
}

async function updateJsonVersion(filePath, nextVersion) {
  const { text: raw, identity, parentIdentity } = await readTextFile(filePath, "version JSON file");
  const data = JSON.parse(raw);
  if (data.version === nextVersion) {
    return;
  }
  data.version = nextVersion;
  await writeIfChanged(filePath, `${JSON.stringify(data, null, 2)}\n`, raw, identity, parentIdentity);
}

async function updateTomlPackageVersion(filePath, expectedName, nextVersion) {
  const { text: raw, identity, parentIdentity } = await readTextFile(filePath, "Cargo manifest");
  const packageHeader = raw.search(/^\[package\]\s*$/m);
  if (packageHeader < 0) {
    throw new Error(`Missing [package] section in ${path.relative(repoRoot, filePath)}`);
  }

  const afterHeader = raw.slice(packageHeader + "[package]".length);
  const nextHeaderOffset = afterHeader.search(/^\[/m);
  const blockEnd = nextHeaderOffset < 0 ? raw.length : packageHeader + "[package]".length + nextHeaderOffset;
  const beforeBlock = raw.slice(0, packageHeader);
  const packageBlock = raw.slice(packageHeader, blockEnd);
  const afterBlock = raw.slice(blockEnd);

  if (!new RegExp(`^name\\s*=\\s*"${escapeRegExp(expectedName)}"\\s*$`, "m").test(packageBlock)) {
    throw new Error(`Unexpected package name in ${path.relative(repoRoot, filePath)}`);
  }

  const nextBlock = replaceRequired(
    packageBlock,
    /^version\s*=\s*"[^"]+"\s*$/m,
    `version = "${nextVersion}"`,
    `Missing package version in ${path.relative(repoRoot, filePath)}`,
  );
  await writeIfChanged(filePath, `${beforeBlock}${nextBlock}${afterBlock}`, raw, identity, parentIdentity);
}

async function updateCargoLockPackageVersion(filePath, packageName, nextVersion) {
  const { text: raw, identity, parentIdentity } = await readTextFile(filePath, "Cargo lockfile");
  const pattern = new RegExp(
    `(^\\[\\[package\\]\\]\\r?\\nname = "${escapeRegExp(packageName)}"\\r?\\nversion = ")[^"]+(")`,
    "m",
  );
  if (!pattern.test(raw)) {
    throw new Error(`Missing ${packageName} package in ${path.relative(repoRoot, filePath)}`);
  }
  await writeIfChanged(filePath, raw.replace(pattern, `$1${nextVersion}$2`), raw, identity, parentIdentity);
}

async function updateOptionalTextFile(filePath, nextText) {
  if (!(await pathExists(filePath))) {
    return;
  }
  const { text: raw, identity, parentIdentity } = await readTextFile(filePath, "optional version file");
  await writeIfChanged(filePath, nextText, raw, identity, parentIdentity);
}

async function writeIfChanged(filePath, nextText, previousText, previousIdentity, previousParentIdentity) {
  if (nextText === previousText) {
    return;
  }
  assertRegularFileWithoutLinks(filePath, "version destination file");
  const parentIdentity = await lstat(path.dirname(filePath), { bigint: true });
  if (!sameFilesystemIdentity(previousParentIdentity, parentIdentity)) {
    throw new Error("version destination parent identity changed after reading");
  }
  const stagingPath = portableSiblingPath(filePath, `.tmp-${randomUUID()}`, "temporary version staging file");
  let stagingHandle = null;
  let stagingIdentity = null;
  try {
    stagingHandle = await open(stagingPath, "wx", 0o600);
    stagingIdentity = await stagingHandle.stat({ bigint: true });
    await stagingHandle.writeFile(nextText, { encoding: "utf8" });
    await stagingHandle.sync();
    await stagingHandle.close();
    stagingHandle = null;

    const currentStagingIdentity = await lstat(stagingPath, { bigint: true });
    if (!sameFilesystemIdentity(stagingIdentity, currentStagingIdentity)) {
      throw new Error("temporary version staging file identity changed");
    }
    await replaceFileTransactionally(stagingPath, filePath, {
      expectedDestinationIdentity: previousIdentity,
      expectedParentIdentity: parentIdentity,
      expectedStagingIdentity: stagingIdentity,
      field: "version file publication",
    });
  } finally {
    await stagingHandle?.close();
    if (stagingIdentity !== null) {
      await removeFileWithoutLinks(stagingPath, {
        expectedIdentity: stagingIdentity,
        expectedParentIdentity: parentIdentity,
        field: "temporary version staging file",
        missingOk: true,
      });
    }
  }
  changes.push(filePath);
}

async function readTextFile(filePath, field) {
  const snapshot = await readRegularFileWithoutLinks(filePath, {
    field,
    encoding: "utf8",
  });
  return {
    identity: snapshot.identity,
    parentIdentity: snapshot.parentIdentity,
    text: snapshot.data,
  };
}

async function pathExists(filePath) {
  try {
    await lstat(filePath);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

function replaceRequired(text, pattern, replacement, errorMessage) {
  if (!pattern.test(text)) {
    throw new Error(errorMessage);
  }
  return text.replace(pattern, replacement);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
