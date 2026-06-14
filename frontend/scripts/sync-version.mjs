import { access, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const versionPath = path.join(repoRoot, "VERSION");

const version = (await readFile(versionPath, "utf8")).trim();
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
  const raw = await readFile(filePath, "utf8");
  const data = JSON.parse(raw);
  if (data.version === nextVersion) {
    return;
  }
  data.version = nextVersion;
  await writeIfChanged(filePath, `${JSON.stringify(data, null, 2)}\n`, raw);
}

async function updateTomlPackageVersion(filePath, expectedName, nextVersion) {
  const raw = await readFile(filePath, "utf8");
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
  await writeIfChanged(filePath, `${beforeBlock}${nextBlock}${afterBlock}`, raw);
}

async function updateCargoLockPackageVersion(filePath, packageName, nextVersion) {
  const raw = await readFile(filePath, "utf8");
  const pattern = new RegExp(
    `(^\\[\\[package\\]\\]\\r?\\nname = "${escapeRegExp(packageName)}"\\r?\\nversion = ")[^"]+(")`,
    "m",
  );
  if (!pattern.test(raw)) {
    throw new Error(`Missing ${packageName} package in ${path.relative(repoRoot, filePath)}`);
  }
  await writeIfChanged(filePath, raw.replace(pattern, `$1${nextVersion}$2`), raw);
}

async function updateOptionalTextFile(filePath, nextText) {
  if (!(await pathExists(filePath))) {
    return;
  }
  const raw = await readFile(filePath, "utf8");
  await writeIfChanged(filePath, nextText, raw);
}

async function writeIfChanged(filePath, nextText, previousText) {
  if (nextText === previousText) {
    return;
  }
  await writeFile(filePath, nextText, "utf8");
  changes.push(filePath);
}

async function pathExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
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
