import { spawnSync } from "node:child_process";
import { link, lstat, mkdtemp, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  assertRegularFileWithoutLinks,
  assertSafeMutableDirectory,
  captureExecutableSnapshot,
  readRegularFileWithoutLinks,
  removeDirectoryWithoutLinks,
  resolveAbsoluteEnvironmentPath,
  resolveExactRelativePath,
  requireExecutableSnapshot,
  sameFilesystemIdentity,
  sha256RegularFileWithoutLinks,
} from "./path-contract.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const targetDir = assertSafeMutableDirectory(
  resolveAbsoluteEnvironmentPath(
    "SHINSEKAI_TAURI_TARGET_DIR",
    path.join(frontendDir, "src-tauri", "target", "release"),
  ),
  { field: "SHINSEKAI_TAURI_TARGET_DIR" },
);
const args = parseArgs(process.argv.slice(2));
const expectedTarget = args.target ?? process.env.SHINSEKAI_RUNTIME_TARGET ?? null;
const requireInstallers = args.requireInstallers;
const installerBundles = args.installerBundles;
const targetDirectoryIdentity = await requireDirectoryIdentity(targetDir, null, "Tauri target directory");

const runtimeMarkerFile = ".shinsekai-runtime.json";
const runtimeMarkerPaths = await findFiles(targetDir, runtimeMarkerFile);

const appRoots = unique(
  runtimeMarkerPaths
    .filter((markerPath) => path.basename(path.dirname(markerPath)) === "runtime")
    .map((markerPath) => path.dirname(path.dirname(markerPath))),
);

if (appRoots.length === 0) {
  throw new Error(`no packaged embedded Python runtime markers found under ${relative(targetDir)}`);
}

let verifiedCount = 0;
let packageSuffixes = null;
const verifiedRoots = [];
for (const appRoot of appRoots) {
  const runtimeRoot = path.join(appRoot, "runtime");
  const runtimeMarker = await readJson(path.join(runtimeRoot, runtimeMarkerFile));

  if (runtimeMarker.source !== "python-build-standalone") {
    throw new Error(`${relative(runtimeRoot)} has unexpected runtime source ${runtimeMarker.source}`);
  }
  if (expectedTarget && runtimeMarker.target !== expectedTarget) {
    throw new Error(`${relative(runtimeRoot)} target ${runtimeMarker.target} does not match ${expectedTarget}`);
  }

  await assertRegularFile(runtimePythonPath(runtimeRoot, runtimeMarker));
  if (!Array.isArray(runtimeMarker.requiredFiles)) {
    throw new Error(`${relative(runtimeRoot)} marker requiredFiles must be an array`);
  }
  for (const requiredFile of runtimeMarker.requiredFiles) {
    await assertRegularFile(resolveExactRelativePath(runtimeRoot, requiredFile, "packaged runtime required file"));
  }
  await assertRegularFile(path.join(appRoot, "runtime_manifest.json"));
  await assertRegularFile(path.join(appRoot, "requirements-runtime-core.txt"));
  packageSuffixes ??= packageRequiredSuffixes(runtimeMarker);
  verifiedRoots.push(
    `${relative(appRoot)} target=${runtimeMarker.target} triple=${runtimeMarker.triple} python=${runtimeMarker.python}`,
  );
  verifiedCount += 1;
}

const inspectedPackages = [];
if (packageSuffixes) {
  inspectedPackages.push(...(await verifyDebPackages(packageSuffixes)));
  inspectedPackages.push(...(await verifyRpmPackages(packageSuffixes)));
}

let installerArtifacts = [];
if (requireInstallers) {
  installerArtifacts = await verifyInstallerArtifacts(expectedTarget, installerBundles);
}
const currentRuntimeMarkerPaths = await findFiles(targetDir, runtimeMarkerFile);
if (
  JSON.stringify(runtimeMarkerPaths.map((value) => path.resolve(value)).sort()) !==
  JSON.stringify(currentRuntimeMarkerPaths.map((value) => path.resolve(value)).sort())
) {
  throw new Error("packaged runtime marker set changed during verification");
}
await requireDirectoryIdentity(targetDir, targetDirectoryIdentity, "Tauri target directory");

for (const root of verifiedRoots) {
  console.log(`Runtime output: ${root}`);
}
for (const packagePath of inspectedPackages) {
  console.log(`Package listing verified: ${packagePath}`);
}
for (const artifact of installerArtifacts) {
  console.log(`Installer artifact: ${artifact}`);
}
console.log(`Verified packaged embedded Python runtime in ${verifiedCount} build output location(s)`);

function parseArgs(argv) {
  const parsed = {
    installerBundles: null,
    requireInstallers: false,
    target: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--target") {
      parsed.target = argv[++index] ?? null;
    } else if (arg.startsWith("--target=")) {
      parsed.target = arg.slice("--target=".length);
    } else if (arg === "--require-installers") {
      parsed.requireInstallers = true;
    } else if (arg === "--installer-bundles") {
      parsed.installerBundles = splitBundles(argv[++index] ?? "");
    } else if (arg.startsWith("--installer-bundles=")) {
      parsed.installerBundles = splitBundles(arg.slice("--installer-bundles=".length));
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return parsed;
}

async function findFiles(root, basename) {
  const matches = [];
  await walk(root, matches, basename);
  return matches;
}

async function findPackageFiles(root, extension) {
  const matches = [];
  await walkPackageFiles(root, matches, extension);
  return matches;
}

async function walk(directory, matches, basename) {
  let directoryIdentity;
  try {
    directoryIdentity = await lstat(directory, { bigint: true });
  } catch (error) {
    if (error?.code === "ENOENT") {
      return;
    }
    throw error;
  }
  if (!directoryIdentity.isDirectory() || directoryIdentity.isSymbolicLink()) {
    throw new Error(`package search root must be a regular non-link directory: ${directory}`);
  }
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = resolveExactRelativePath(directory, entry.name, "package search entry");
    const entryIdentity = await lstat(entryPath, { bigint: true });
    if (entryIdentity.isSymbolicLink()) {
      continue;
    }
    if (entryIdentity.isDirectory()) {
      if (shouldSkipDirectory(entry.name)) {
        continue;
      }
      await walk(entryPath, matches, basename);
    } else if (entryIdentity.isFile() && entry.name === basename) {
      matches.push(entryPath);
    }
  }
  const currentIdentity = await lstat(directory, { bigint: true });
  if (!sameStableDirectoryState(directoryIdentity, currentIdentity)) {
    throw new Error(`package search directory changed during traversal: ${directory}`);
  }
}

function shouldSkipDirectory(name) {
  return ["build", "deps", "examples", "incremental"].includes(name);
}

async function walkPackageFiles(directory, matches, extension) {
  let directoryIdentity;
  try {
    directoryIdentity = await lstat(directory, { bigint: true });
  } catch (error) {
    if (error?.code === "ENOENT") {
      return;
    }
    throw error;
  }
  if (!directoryIdentity.isDirectory() || directoryIdentity.isSymbolicLink()) {
    throw new Error(`installer search root must be a regular non-link directory: ${directory}`);
  }
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = resolveExactRelativePath(directory, entry.name, "installer search entry");
    const entryIdentity = await lstat(entryPath, { bigint: true });
    if (entryIdentity.isSymbolicLink()) {
      continue;
    }
    if (entryIdentity.isDirectory()) {
      await walkPackageFiles(entryPath, matches, extension);
    } else if (entryIdentity.isFile() && entry.name.endsWith(extension)) {
      matches.push(entryPath);
    }
  }
  const currentIdentity = await lstat(directory, { bigint: true });
  if (!sameStableDirectoryState(directoryIdentity, currentIdentity)) {
    throw new Error(`installer search directory changed during traversal: ${directory}`);
  }
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

async function readJson(filePath) {
  try {
    return JSON.parse(
      (
        await readRegularFileWithoutLinks(filePath, {
          field: "packaged runtime JSON file",
          encoding: "utf8",
        })
      ).data,
    );
  } catch (error) {
    throw new Error(`failed to read ${relative(filePath)}: ${error.message}`);
  }
}

async function assertRegularFile(filePath) {
  try {
    assertRegularFileWithoutLinks(filePath, "required packaged runtime file");
  } catch {
    throw new Error(`required packaged runtime file is missing or unsafe: ${relative(filePath)}`);
  }
}

async function verifyDebPackages(requiredSuffixes) {
  const debs = await findPackageFiles(path.join(targetDir, "bundle", "deb"), ".deb");
  const inspected = [];
  for (const deb of debs) {
    const listing = await runPackageListCommand("dpkg-deb", ["-c", deb], deb);
    assertListingContains(listing, requiredSuffixes, deb);
    inspected.push(relative(deb));
  }
  return inspected;
}

async function verifyRpmPackages(requiredSuffixes) {
  const rpms = await findPackageFiles(path.join(targetDir, "bundle", "rpm"), ".rpm");
  const inspected = [];
  for (const rpm of rpms) {
    const listing = await runPackageListCommand("rpm", ["-qlp", rpm], rpm);
    assertListingContains(listing, requiredSuffixes, rpm);
    inspected.push(relative(rpm));
  }
  return inspected;
}

async function verifyInstallerArtifacts(targetName, requestedBundles) {
  if (!targetName) {
    throw new Error("--require-installers requires --target or SHINSEKAI_RUNTIME_TARGET");
  }
  const expectedArtifacts = installerArtifactsForTarget(targetName, requestedBundles);
  const artifacts = [];
  for (const artifact of expectedArtifacts) {
    const files = await findPackageFiles(path.join(targetDir, "bundle", artifact.directory), artifact.extension);
    if (files.length === 0) {
      throw new Error(`missing ${artifact.label} installer artifact for ${targetName}`);
    }
    for (const file of files) {
      const artifactPin = await pinRegularFile(file, "installer artifact");
      if (artifactPin.identity.size === 0n) {
        throw new Error(`installer artifact is empty or not a file: ${relative(file)}`);
      }
      artifacts.push(`${relative(file)} size=${artifactPin.identity.size}`);
    }
  }
  return artifacts;
}

async function pinRegularFile(filePath, field) {
  const snapshot = await sha256RegularFileWithoutLinks(filePath, {
    field,
  });
  return {
    path: filePath,
    field,
    identity: snapshot.identity,
    parentIdentity: snapshot.parentIdentity,
    sha256: snapshot.sha256,
  };
}

async function requirePinnedFile(pin) {
  return sha256RegularFileWithoutLinks(pin.path, {
    field: pin.field,
    expectedIdentity: pin.identity,
    expectedParentIdentity: pin.parentIdentity,
    expectedSha256: pin.sha256,
  });
}

async function requireDirectoryIdentity(target, expectedIdentity, field) {
  const identity = await lstat(target, { bigint: true });
  if (
    !identity.isDirectory() ||
    identity.isSymbolicLink() ||
    (expectedIdentity !== null && !sameFilesystemIdentity(expectedIdentity, identity))
  ) {
    throw new Error(`${field} identity changed`);
  }
  return identity;
}

function installerArtifactsForTarget(targetName, requestedBundles) {
  const supportedArtifacts = supportedInstallerArtifactsForTarget(targetName);
  const supportedBundles = new Set(supportedArtifacts.map((artifact) => artifact.bundle));
  const requiredBundles =
    requestedBundles && requestedBundles.length > 0 ? unique(requestedBundles) : [...supportedBundles];
  const unsupportedBundles = requiredBundles.filter((bundle) => !supportedBundles.has(bundle));
  if (unsupportedBundles.length > 0) {
    throw new Error(`unsupported installer bundle(s) for ${targetName}: ${unsupportedBundles.join(", ")}`);
  }
  return supportedArtifacts.filter((artifact) => requiredBundles.includes(artifact.bundle));
}

function supportedInstallerArtifactsForTarget(targetName) {
  if (targetName.startsWith("linux-")) {
    return [
      { bundle: "deb", directory: "deb", extension: ".deb", label: "deb" },
      { bundle: "rpm", directory: "rpm", extension: ".rpm", label: "rpm" },
      { bundle: "appimage", directory: "appimage", extension: ".AppImage", label: "AppImage" },
    ];
  }
  if (targetName.startsWith("windows-")) {
    return [
      { bundle: "msi", directory: "msi", extension: ".msi", label: "MSI" },
      { bundle: "nsis", directory: "nsis", extension: ".exe", label: "NSIS" },
    ];
  }
  if (targetName.startsWith("macos-")) {
    return [{ bundle: "dmg", directory: "dmg", extension: ".dmg", label: "DMG" }];
  }
  throw new Error(`unsupported runtime target for installer verification: ${targetName}`);
}

async function runPackageListCommand(command, args, packagePath) {
  const packagePin = await pinRegularFile(packagePath, "packaged installer");
  const packageParent = path.dirname(packagePath);
  const verificationRoot = await mkdtemp(path.join(packageParent, ".package-list-"));
  const verificationRootIdentity = await requireDirectoryIdentity(
    verificationRoot,
    null,
    "package listing verification directory",
  );
  const privatePackagePath = path.join(verificationRoot, path.basename(packagePath));
  try {
    await link(packagePath, privatePackagePath);
    const privateIdentity = await lstat(privatePackagePath, { bigint: true });
    if (!sameFilesystemIdentity(packagePin.identity, privateIdentity)) {
      throw new Error("packaged installer identity changed before inspection");
    }
    const privatePin = {
      path: privatePackagePath,
      field: "private packaged installer",
      identity: privateIdentity,
      parentIdentity: verificationRootIdentity,
      sha256: packagePin.sha256,
    };
    await requirePinnedFile(packagePin);
    await requirePinnedFile(privatePin);
    const privateArgs = args.map((argument) => (argument === packagePath ? privatePackagePath : argument));
    const executable = captureExecutableSnapshot(command, {
      field: `package listing command ${JSON.stringify(command)}`,
    });
    const executablePath = requireExecutableSnapshot(executable, `package listing command ${JSON.stringify(command)}`);
    let result;
    try {
      result = spawnSync(executablePath, privateArgs, {
        cwd: verificationRoot,
        encoding: "utf8",
        env: sanitizedPackageListerEnvironment(command),
        stdio: ["ignore", "pipe", "pipe"],
      });
    } finally {
      requireExecutableSnapshot(executable, `package listing command ${JSON.stringify(command)}`);
    }
    await requirePinnedFile(packagePin);
    await requirePinnedFile(privatePin);
    if (result.error) {
      throw new Error(`failed to inspect ${relative(packagePath)} with ${command}: ${result.error.message}`);
    }
    if (result.status !== 0) {
      throw new Error(
        `failed to inspect ${relative(packagePath)} with ${command}: ${
          result.stderr || result.stdout || `exit ${result.status}`
        }`,
      );
    }
    return result.stdout
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
  } finally {
    await removeDirectoryWithoutLinks(verificationRoot, {
      expectedIdentity: verificationRootIdentity,
      expectedParentIdentity: packagePin.parentIdentity,
      field: "package listing verification directory",
      missingOk: true,
    });
  }
}

function sanitizedPackageListerEnvironment(command) {
  const env = { ...process.env };
  if (command === "rpm") {
    delete env.RPM_CONFIGDIR;
    delete env.RPM_MACROS;
  }
  if (command === "dpkg-deb") {
    delete env.DPKG_ADMINDIR;
    delete env.DPKG_ROOT;
  }
  return env;
}

function assertListingContains(listing, requiredSuffixes, packagePath) {
  for (const suffix of requiredSuffixes) {
    if (!listing.some((entry) => normalizeListingPath(entry).endsWith(suffix))) {
      throw new Error(`${relative(packagePath)} is missing packaged runtime entry ending with ${suffix}`);
    }
  }
}

function normalizeListingPath(entry) {
  const parts = entry.split(/\s+/);
  return (parts[parts.length - 1] ?? entry).replace(/^\.\//, "/");
}

function packageRequiredSuffixes(marker) {
  return [
    "runtime_manifest.json",
    "requirements-runtime-core.txt",
    "runtime/.shinsekai-runtime.json",
    ...new Set((marker.requiredFiles ?? []).map((requiredFile) => `runtime/${requiredFile}`)),
  ];
}

function runtimePythonPath(runtimeRoot, marker) {
  if (marker.target?.startsWith("windows-")) {
    return path.join(runtimeRoot, "python.exe");
  }
  const version = /^([0-9]+)\.([0-9]+)(?:\.[0-9]+)?$/u.exec(String(marker.python ?? ""));
  if (version) {
    return path.join(runtimeRoot, "bin", `python${version[1]}.${version[2]}`);
  }
  throw new Error(`packaged runtime marker has an invalid Python version: ${String(marker.python ?? "")}`);
}

function unique(values) {
  return [...new Set(values)];
}

function splitBundles(value) {
  return String(value)
    .split(",")
    .map((bundle) => bundle.trim().toLowerCase())
    .filter(Boolean);
}

function relative(filePath) {
  return path.relative(frontendDir, filePath) || ".";
}
