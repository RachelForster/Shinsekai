import { createHash } from "node:crypto";
import { createWriteStream, existsSync } from "node:fs";
import { access, cp, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { get } from "node:https";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const runtimeSourcesPath = path.join(frontendDir, "src-tauri", "runtime_sources.json");
const defaultCacheDir = path.join(repoRoot, ".cache", "python-build-standalone");
const runtimeMarkerFile = ".shinsekai-runtime.json";
const wheelsMarkerFile = ".shinsekai-wheels.json";

const args = parseArgs(process.argv.slice(2));
const runtimeSources = JSON.parse(await readFile(runtimeSourcesPath, "utf8"));

if (args.printTargets) {
  for (const [target, config] of Object.entries(runtimeSources.targets ?? {})) {
    console.log(`${target} ${config.python} ${config.triple} ${config.asset}`);
  }
  process.exit(0);
}

const targetName = args.target ?? process.env.SHINSEKAI_RUNTIME_TARGET ?? inferTarget();
const target = runtimeSources.targets?.[targetName];
if (!target) {
  throw new Error(
    `Unsupported runtime target "${targetName}". Available targets: ${Object.keys(runtimeSources.targets ?? {}).join(
      ", ",
    )}`,
  );
}

const cacheDir = path.resolve(process.env.SHINSEKAI_PBS_CACHE_DIR ?? defaultCacheDir);
const outputRuntime = path.resolve(process.env.SHINSEKAI_RUNTIME_OUTPUT_DIR ?? path.join(repoRoot, "runtime"));
const wheelsDir = path.resolve(
  process.env.SHINSEKAI_RUNTIME_WHEEL_DIR ?? path.join(repoRoot, runtimeSources.wheels?.directory ?? "wheels"),
);
const skipWheels = args.skipWheels || envFlag("SHINSEKAI_SKIP_RUNTIME_WHEELS");
const force = args.force || envFlag("SHINSEKAI_FORCE_RUNTIME");

await prepareRuntime(targetName, target);
if (!skipWheels) {
  await prepareWheels(targetName, target);
  if (args.verify) {
    await verifyWheelhouse(targetName);
  }
}

async function prepareRuntime(targetName, target) {
  if (!force && (await markerMatches(path.join(outputRuntime, runtimeMarkerFile), runtimeMarker(targetName, target)))) {
    console.log(`Embedded Python runtime is already prepared at ${relative(outputRuntime)}`);
    return;
  }

  const archivePath = path.join(cacheDir, runtimeSources.release, target.asset);
  await mkdir(path.dirname(archivePath), { recursive: true });
  if (!(await fileSha256Matches(archivePath, target.sha256))) {
    await downloadRuntimeArchive(target, archivePath);
  }
  await assertFileSha256(archivePath, target.sha256);

  const extractRoot = path.join(cacheDir, runtimeSources.release, `extract-${targetName}-${process.pid}-${Date.now()}`);
  await rm(extractRoot, { force: true, recursive: true });
  await mkdir(extractRoot, { recursive: true });
  try {
    const tarArchivePathArg = toPosixRelativePath(extractRoot, archivePath);
    console.log(`Extracting ${target.asset} into ${relative(extractRoot)}`);
    const extract = spawnSync("tar", ["-xzf", tarArchivePathArg], {
      cwd: extractRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (extract.status !== 0) {
      throw new Error(
        `tar failed for ${target.asset}: ${extract.stderr || extract.stdout || `exit ${extract.status}`}`,
      );
    }

    const archiveRuntimeRoot = await archiveRuntimePath(extractRoot);
    const stagingRuntime = `${outputRuntime}.tmp-${process.pid}-${Date.now()}`;
    await rm(stagingRuntime, { force: true, recursive: true });
    await cp(archiveRuntimeRoot, stagingRuntime, { dereference: true, force: true, recursive: true });
    const prunedFiles = await pruneRuntimeFiles(stagingRuntime, target.prune_files ?? []);
    if (prunedFiles.length > 0) {
      console.log(`Pruned ${prunedFiles.length} runtime file(s): ${prunedFiles.join(", ")}`);
    }
    await verifyRequiredRuntimeFiles(stagingRuntime, target);
    await writeFile(
      path.join(stagingRuntime, runtimeMarkerFile),
      `${JSON.stringify(runtimeMarker(targetName, target), null, 2)}\n`,
    );
    await rm(outputRuntime, { force: true, recursive: true });
    await rename(stagingRuntime, outputRuntime);
    console.log(`Prepared embedded Python runtime ${target.python} for ${targetName} at ${relative(outputRuntime)}`);
  } finally {
    await rm(extractRoot, { force: true, recursive: true });
  }
}

async function verifyRequiredRuntimeFiles(runtimeRoot, target) {
  for (const requiredFile of target.required_files ?? []) {
    await assertExists(path.join(runtimeRoot, requiredFile), `runtime archive missing required file ${requiredFile}`);
  }
}

async function pruneRuntimeFiles(runtimeRoot, patterns) {
  if (!Array.isArray(patterns) || patterns.length === 0) {
    return [];
  }
  const matchers = patterns.map(globPatternToRegExp);
  const prunedFiles = [];
  await pruneRuntimeFilesInDirectory(runtimeRoot, runtimeRoot, matchers, prunedFiles);
  return prunedFiles;
}

async function pruneRuntimeFilesInDirectory(runtimeRoot, directory, matchers, prunedFiles) {
  let entries;
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    const relativePath = toPosixPath(path.relative(runtimeRoot, entryPath));
    if (matchers.some((matcher) => matcher.test(relativePath))) {
      await rm(entryPath, { force: true, recursive: true });
      prunedFiles.push(relativePath);
      continue;
    }
    if (entry.isDirectory()) {
      await pruneRuntimeFilesInDirectory(runtimeRoot, entryPath, matchers, prunedFiles);
    }
  }
}

async function downloadRuntimeArchive(target, archivePath) {
  const urls = runtimeDownloadUrls(target.asset);
  let lastError = null;
  for (const url of urls) {
    try {
      await downloadFile(url, archivePath);
      console.log(`Downloaded ${target.asset} from ${url}`);
      return;
    } catch (error) {
      lastError = error;
      await rm(archivePath, { force: true });
      console.warn(`Failed to download ${target.asset} from ${url}: ${error.message}`);
    }
  }
  throw new Error(`failed to download ${target.asset} from all configured bases: ${lastError?.message ?? "unknown"}`);
}

async function prepareWheels(targetName, target) {
  const requirements = runtimeSources.wheels?.requirements ?? ["requirements-runtime-core.txt"];
  const bootstrap = runtimeSources.wheels?.bootstrap ?? {};
  const wheelMarker = {
    schema: 1,
    target: targetName,
    release: runtimeSources.release,
    provider: runtimeSources.provider,
    python: target.python,
    triple: target.triple,
    requirements,
    bootstrap,
  };
  if (
    (await markerMatches(path.join(wheelsDir, wheelsMarkerFile), wheelMarker)) &&
    (await directoryHasEntries(wheelsDir))
  ) {
    console.log(`Runtime wheels are already prepared at ${relative(wheelsDir)}`);
    return;
  }

  const python = pythonInPrefix(outputRuntime);
  if (!python) {
    throw new Error(`prepared runtime does not contain a Python executable: ${outputRuntime}`);
  }

  const stagingWheels = `${wheelsDir}.tmp-${process.pid}-${Date.now()}`;
  await rm(stagingWheels, { force: true, recursive: true });
  await mkdir(stagingWheels, { recursive: true });
  try {
    await prepareBootstrapWheelhouse(stagingWheels, bootstrap, python);
    for (const requirement of requirements) {
      const requirementPath = path.join(repoRoot, requirement);
      const env = { ...process.env };
      delete env.PYTHONHOME;
      delete env.PYTHONPATH;
      env.PIP_DISABLE_PIP_VERSION_CHECK = "1";
      const download = spawnSync(
        python,
        ["-m", "pip", "download", "--dest", stagingWheels, ...pipIndexArgs(), "-r", requirementPath],
        {
          cwd: repoRoot,
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
          env,
        },
      );
      if (download.status !== 0) {
        throw new Error(
          `pip download failed for ${requirement}: ${download.stderr || download.stdout || `exit ${download.status}`}`,
        );
      }
    }
    await writeFile(path.join(stagingWheels, wheelsMarkerFile), `${JSON.stringify(wheelMarker, null, 2)}\n`);
    await rm(wheelsDir, { force: true, recursive: true });
    await rename(stagingWheels, wheelsDir);
    console.log(`Prepared runtime wheels for ${targetName} at ${relative(wheelsDir)}`);
  } finally {
    await rm(stagingWheels, { force: true, recursive: true });
  }
}

async function prepareBootstrapWheelhouse(stagingWheels, bootstrap, python) {
  if (bootstrap.get_pip?.url) {
    const getPipPath = path.join(stagingWheels, "get-pip.py");
    await downloadFile(bootstrap.get_pip.url, getPipPath);
    if (bootstrap.get_pip.sha256) {
      await assertFileSha256(getPipPath, bootstrap.get_pip.sha256);
    }
  }
  const packages = bootstrap.packages ?? [];
  if (packages.length === 0) {
    return;
  }
  const env = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.PIP_DISABLE_PIP_VERSION_CHECK = "1";
  const download = spawnSync(
    python,
    ["-m", "pip", "download", "--dest", stagingWheels, ...pipIndexArgs(), ...packages],
    {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      env,
    },
  );
  if (download.status !== 0) {
    throw new Error(
      `pip download failed for bootstrap packages ${packages.join(", ")}: ${
        download.stderr || download.stdout || `exit ${download.status}`
      }`,
    );
  }
}

async function verifyWheelhouse(targetName) {
  const python = pythonInPrefix(outputRuntime);
  if (!python) {
    throw new Error(`prepared runtime does not contain a Python executable: ${outputRuntime}`);
  }
  const requirements = runtimeSources.wheels?.requirements ?? ["requirements-runtime-core.txt"];
  for (const requirement of requirements) {
    const requirementPath = path.join(repoRoot, requirement);
    const verify = spawnSync(
      python,
      ["-m", "pip", "install", "--dry-run", "--no-index", "--find-links", wheelsDir, "-r", requirementPath],
      {
        cwd: repoRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    if (verify.status !== 0) {
      throw new Error(
        `offline wheelhouse verification failed for ${targetName} ${requirement}: ${
          verify.stderr || verify.stdout || `exit ${verify.status}`
        }`,
      );
    }
  }
  console.log(`Verified offline runtime wheels for ${targetName}`);
}

function runtimeDownloadUrls(assetName) {
  const envBases = [process.env.SHINSEKAI_PBS_BASE_URL, process.env.SHINSEKAI_PBS_DOWNLOAD_BASES]
    .filter(Boolean)
    .flatMap((value) => splitList(value));
  const bases = envBases.length > 0 ? envBases : (runtimeSources.base_urls ?? []);
  return unique(bases.map((base) => new URL(encodeURIComponent(assetName), ensureTrailingSlash(base)).toString()));
}

function pipIndexArgs() {
  const urls = [process.env.SHINSEKAI_PIP_INDEX_URL, ...splitList(process.env.SHINSEKAI_PIP_INDEX_URLS)].filter(
    Boolean,
  );
  if (urls.length === 0) {
    return [];
  }
  return urls.flatMap((url, index) => (index === 0 ? ["-i", url] : ["--extra-index-url", url]));
}

async function archiveRuntimePath(extractRoot) {
  const configured = runtimeSources.archive_root;
  if (configured) {
    const candidate = path.join(extractRoot, configured);
    if (await pathExists(candidate)) {
      return candidate;
    }
  }
  const entries = await readdir(extractRoot, { withFileTypes: true });
  const directories = entries.filter((entry) => entry.isDirectory());
  if (directories.length === 1) {
    return path.join(extractRoot, directories[0].name);
  }
  throw new Error(`could not locate runtime root after extracting archive into ${extractRoot}`);
}

function runtimeMarker(targetName, target) {
  return {
    schema: 2,
    source: runtimeSources.provider,
    release: runtimeSources.release,
    target: targetName,
    python: target.python,
    triple: target.triple,
    asset: target.asset,
    sha256: target.sha256,
    requiredFiles: target.required_files ?? [],
    prunedFiles: target.prune_files ?? [],
    profile: "desktop-core",
  };
}

function parseArgs(argv) {
  const parsed = {
    printTargets: false,
    force: false,
    skipWheels: false,
    target: null,
    verify: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--") {
      continue;
    } else if (arg === "--force") {
      parsed.force = true;
    } else if (arg === "--print-targets") {
      parsed.printTargets = true;
    } else if (arg === "--verify") {
      parsed.verify = true;
    } else if (arg === "--skip-wheels") {
      parsed.skipWheels = true;
    } else if (arg === "--target") {
      parsed.target = argv[++index];
    } else if (arg.startsWith("--target=")) {
      parsed.target = arg.slice("--target=".length);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return parsed;
}

function inferTarget() {
  const platform =
    process.platform === "win32"
      ? "windows"
      : process.platform === "darwin"
        ? "macos"
        : process.platform === "linux"
          ? "linux"
          : null;
  const arch = process.arch === "x64" ? "x64" : process.arch === "arm64" ? "arm64" : null;
  if (!platform || !arch) {
    throw new Error(`Cannot infer runtime target for platform=${process.platform} arch=${process.arch}`);
  }
  return `${platform}-${arch}`;
}

function pythonInPrefix(prefix) {
  const candidates = [
    path.join(prefix, "bin", "python3"),
    path.join(prefix, "bin", "python"),
    path.join(prefix, "bin", "python3.13"),
    path.join(prefix, "bin", "python3.12"),
    path.join(prefix, "bin", "python3.11"),
    path.join(prefix, "bin", "python3.10"),
    path.join(prefix, "Scripts", "python.exe"),
    path.join(prefix, "Scripts", "python"),
    path.join(prefix, "python.exe"),
  ];
  return candidates.find((candidate) => existsSync(candidate));
}

async function downloadFile(url, outputPath) {
  await mkdir(path.dirname(outputPath), { recursive: true });
  const tempPath = `${outputPath}.download-${process.pid}-${Date.now()}`;
  await rm(tempPath, { force: true });
  try {
    try {
      await downloadFileWithCurl(url, tempPath);
    } catch (error) {
      if (!isMissingCommandError(error)) {
        throw error;
      }
      await downloadFileWithNodeHttps(url, tempPath);
    }
    await rename(tempPath, outputPath);
  } finally {
    await rm(tempPath, { force: true });
  }
}

async function downloadFileWithCurl(url, outputPath) {
  const timeoutSeconds = process.env.SHINSEKAI_DOWNLOAD_TIMEOUT_SECONDS ?? "900";
  const download = spawnSync(
    "curl",
    [
      "--fail",
      "--location",
      "--retry",
      "3",
      "--connect-timeout",
      "30",
      "--max-time",
      timeoutSeconds,
      "--progress-bar",
      "--output",
      outputPath,
      url,
    ],
    {
      stdio: ["ignore", "inherit", "inherit"],
    },
  );
  if (download.error) {
    throw download.error;
  }
  if (download.status !== 0) {
    throw new Error(`curl exited with status ${download.status}`);
  }
}

async function downloadFileWithNodeHttps(url, outputPath) {
  const timeoutMs = Number(process.env.SHINSEKAI_DOWNLOAD_TIMEOUT_SECONDS ?? "900") * 1000;
  await new Promise((resolve, reject) => {
    let request;
    const timeout = setTimeout(() => {
      request?.destroy(new Error(`download timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
    request = get(url, (response) => {
      if (response.statusCode && response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        clearTimeout(timeout);
        downloadFileWithNodeHttps(new URL(response.headers.location, url).toString(), outputPath).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        clearTimeout(timeout);
        reject(new Error(`HTTP ${response.statusCode}`));
        return;
      }
      const file = createWriteStream(outputPath);
      response.pipe(file);
      file.on("finish", () => {
        clearTimeout(timeout);
        file.close(resolve);
      });
      file.on("error", (error) => {
        clearTimeout(timeout);
        reject(error);
      });
    });
    request.setTimeout(30_000, () => request.destroy(new Error("connection timed out")));
    request.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
  });
}

function isMissingCommandError(error) {
  return error?.code === "ENOENT";
}

async function fileSha256Matches(target, expected) {
  if (!expected || !(await pathExists(target))) {
    return false;
  }
  return (await sha256File(target)) === normalizeSha256(expected);
}

async function assertFileSha256(target, expected) {
  const actual = await sha256File(target);
  const normalizedExpected = normalizeSha256(expected);
  if (actual !== normalizedExpected) {
    throw new Error(`sha256 mismatch for ${target}: expected ${normalizedExpected}, got ${actual}`);
  }
}

async function sha256File(target) {
  const hash = createHash("sha256");
  hash.update(await readFile(target));
  return hash.digest("hex");
}

async function markerMatches(markerPath, expected) {
  try {
    const actual = JSON.parse(await readFile(markerPath, "utf8"));
    return JSON.stringify(actual) === JSON.stringify(expected);
  } catch {
    return false;
  }
}

async function directoryHasEntries(directory) {
  try {
    const entries = await readdir(directory);
    return entries.some((entry) => entry !== wheelsMarkerFile);
  } catch {
    return false;
  }
}

async function pathExists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function assertExists(target, message) {
  try {
    await access(target);
  } catch {
    throw new Error(message);
  }
}

function normalizeSha256(value) {
  return value
    .replace(/^sha256:/, "")
    .trim()
    .toLowerCase();
}

function ensureTrailingSlash(value) {
  return value.endsWith("/") ? value : `${value}/`;
}

function splitList(value) {
  return String(value ?? "")
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function unique(values) {
  return [...new Set(values)];
}

function envFlag(name) {
  return ["1", "true", "yes", "on"].includes(String(process.env[name] ?? "").toLowerCase());
}

function relative(target) {
  return path.relative(repoRoot, target) || ".";
}

function toPosixRelativePath(fromDir, target) {
  const relativePath = path.relative(fromDir, target);
  if (!relativePath || path.isAbsolute(relativePath)) {
    throw new Error(`cannot express ${target} as a relative path from ${fromDir}`);
  }
  return toPosixPath(relativePath);
}

function toPosixPath(value) {
  return value.split(path.sep).join("/");
}

function globPatternToRegExp(pattern) {
  let source = "^";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    const next = pattern[index + 1];
    if (char === "*" && next === "*") {
      source += ".*";
      index += 1;
    } else if (char === "*") {
      source += "[^/]*";
    } else if (char === "?") {
      source += "[^/]";
    } else {
      source += escapeRegExp(char);
    }
  }
  return new RegExp(`${source}$`);
}

function escapeRegExp(value) {
  return value.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&");
}
