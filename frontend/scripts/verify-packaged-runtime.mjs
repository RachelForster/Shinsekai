import { spawnSync } from "node:child_process";
import { access, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const targetDir = path.resolve(
  process.env.SHINSEKAI_TAURI_TARGET_DIR ?? path.join(frontendDir, "src-tauri", "target", "release"),
);
const args = parseArgs(process.argv.slice(2));
const expectedTarget = args.target ?? process.env.SHINSEKAI_RUNTIME_TARGET ?? null;
const requireInstallers = args.requireInstallers;
const installerBundles = args.installerBundles;

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

  await assertExists(runtimePythonPath(runtimeRoot, runtimeMarker));
  for (const requiredFile of runtimeMarker.requiredFiles ?? []) {
    await assertExists(path.join(runtimeRoot, requiredFile));
  }
  await assertExists(path.join(appRoot, "runtime_manifest.json"));
  await assertExists(path.join(appRoot, "requirements-runtime-core.txt"));
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
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (shouldSkipDirectory(entry.name)) {
        continue;
      }
      await walk(entryPath, matches, basename);
    } else if (entry.isFile() && entry.name === basename) {
      matches.push(entryPath);
    }
  }
}

function shouldSkipDirectory(name) {
  return ["build", "deps", "examples", "incremental"].includes(name);
}

async function walkPackageFiles(directory, matches, extension) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      await walkPackageFiles(entryPath, matches, extension);
    } else if (entry.isFile() && entry.name.endsWith(extension)) {
      matches.push(entryPath);
    }
  }
}

async function readJson(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    throw new Error(`failed to read ${relative(filePath)}: ${error.message}`);
  }
}

async function assertExists(filePath) {
  try {
    await access(filePath);
  } catch {
    throw new Error(`required packaged runtime file is missing: ${relative(filePath)}`);
  }
}

async function verifyDebPackages(requiredSuffixes) {
  const debs = await findPackageFiles(path.join(targetDir, "bundle", "deb"), ".deb");
  const inspected = [];
  for (const deb of debs) {
    const listing = runPackageListCommand("dpkg-deb", ["-c", deb], deb);
    assertListingContains(listing, requiredSuffixes, deb);
    inspected.push(relative(deb));
  }
  return inspected;
}

async function verifyRpmPackages(requiredSuffixes) {
  const rpms = await findPackageFiles(path.join(targetDir, "bundle", "rpm"), ".rpm");
  const inspected = [];
  for (const rpm of rpms) {
    const listing = runPackageListCommand("rpm", ["-qlp", rpm], rpm);
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
      const fileStat = await stat(file);
      if (!fileStat.isFile() || fileStat.size === 0) {
        throw new Error(`installer artifact is empty or not a file: ${relative(file)}`);
      }
      artifacts.push(`${relative(file)} size=${fileStat.size}`);
    }
  }
  return artifacts;
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

function runPackageListCommand(command, args, packagePath) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
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
  const [major, minor] = String(marker.python ?? "").split(".");
  if (major && minor) {
    return path.join(runtimeRoot, "bin", `python${major}.${minor}`);
  }
  return path.join(runtimeRoot, "bin", "python3");
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
