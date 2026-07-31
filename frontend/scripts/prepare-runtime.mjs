import { randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { cp, link, lstat, mkdir, mkdtemp, readdir, writeFile } from "node:fs/promises";
import { get } from "node:https";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  assertContainedDirectoryTree,
  assertNonOverlappingDirectories,
  assertRegularFileWithoutLinks,
  assertSafeMutableDirectory,
  captureDirectoryAliasSnapshot,
  captureExecutableSnapshot,
  captureRegularFileAliasSnapshot,
  copyRegularFileExclusiveWithoutLinks,
  portableSiblingPath,
  portableTemporaryPathPrefix,
  readRegularFileWithoutLinks,
  removeDirectoryWithoutLinks,
  removeFileWithoutLinks,
  replaceDirectoryTransactionally,
  replaceFileTransactionally,
  requireDirectorySnapshot,
  requireExecutableSnapshot,
  requireRegularFileSnapshot,
  resolveAbsoluteEnvironmentPath,
  resolveExactRelativePath,
  sameFilesystemIdentity,
  sha256RegularFileWithoutLinks,
  validateArchiveLinkTarget,
  validateArchiveMemberSet,
  validateExactArchiveMemberPath,
} from "./path-contract.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");
const runtimeSourcesPath = path.join(frontendDir, "src-tauri", "runtime_sources.json");
const defaultCacheDir = path.join(repoRoot, ".cache", "python-build-standalone");
const defaultRuntimeOutputDir = path.join(repoRoot, "runtime");
const runtimeMarkerFile = ".shinsekai-runtime.json";
const wheelsMarkerFile = ".shinsekai-wheels.json";
const sourceArchiveSuffixes = [".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".zip"];

const args = parseArgs(process.argv.slice(2));
const runtimeSources = JSON.parse(
  (
    await readRegularFileWithoutLinks(runtimeSourcesPath, {
      field: "runtime source manifest",
      encoding: "utf8",
    })
  ).data,
);

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

const defaultWheelsDir = resolveExactRelativePath(
  repoRoot,
  runtimeSources.wheels?.directory ?? "wheels",
  "runtime wheel directory",
);
const cacheDir = assertSafeMutableDirectory(
  resolveAbsoluteEnvironmentPath("SHINSEKAI_PBS_CACHE_DIR", defaultCacheDir),
  {
    field: "SHINSEKAI_PBS_CACHE_DIR",
    protectedRoots: [repoRoot],
    allowedRoots: [defaultCacheDir],
  },
);
const outputRuntime = assertSafeMutableDirectory(
  resolveAbsoluteEnvironmentPath("SHINSEKAI_RUNTIME_OUTPUT_DIR", defaultRuntimeOutputDir),
  {
    field: "SHINSEKAI_RUNTIME_OUTPUT_DIR",
    protectedRoots: [repoRoot],
    allowedRoots: [defaultRuntimeOutputDir],
  },
);
const wheelsDir = assertSafeMutableDirectory(
  resolveAbsoluteEnvironmentPath("SHINSEKAI_RUNTIME_WHEEL_DIR", defaultWheelsDir),
  {
    field: "SHINSEKAI_RUNTIME_WHEEL_DIR",
    protectedRoots: [repoRoot],
    allowedRoots: [defaultWheelsDir],
  },
);
assertNonOverlappingDirectories([
  { field: "SHINSEKAI_PBS_CACHE_DIR", path: cacheDir },
  { field: "SHINSEKAI_RUNTIME_OUTPUT_DIR", path: outputRuntime },
  { field: "SHINSEKAI_RUNTIME_WHEEL_DIR", path: wheelsDir },
]);
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
    try {
      assertContainedDirectoryTree(outputRuntime, "cached embedded runtime", {
        allowContainedSymbolicLinks: false,
      });
      await verifyRequiredRuntimeFiles(outputRuntime, target);
      console.log(`Embedded Python runtime is already prepared at ${relative(outputRuntime)}`);
      return;
    } catch (error) {
      console.warn(`Cached embedded runtime is incomplete and will be rebuilt: ${error.message}`);
    }
  }
  const outputRuntimeIdentity = await directoryIdentityIfExists(outputRuntime, "embedded Python runtime destination");
  const outputRuntimeParentIdentity = await lstat(path.dirname(outputRuntime), {
    bigint: true,
  });

  const releaseRoot = assertSafeMutableDirectory(
    resolveExactRelativePath(cacheDir, runtimeSources.release, "runtime release directory"),
    { field: "runtime release directory" },
  );
  const archivePath = resolveExactRelativePath(releaseRoot, target.asset, "runtime archive filename");
  await mkdir(path.dirname(archivePath), { recursive: true });
  assertSafeMutableDirectory(releaseRoot, {
    field: "runtime release directory",
  });
  if (!(await fileSha256Matches(archivePath, target.sha256))) {
    await downloadRuntimeArchive(target, archivePath);
  }
  const archiveSnapshot = await assertFileSha256(archivePath, target.sha256);

  const extractRoot = await mkdtemp(
    portableTemporaryPathPrefix(path.join(releaseRoot, `extract-${targetName}-`), {
      field: "runtime extraction temporary prefix",
    }),
  );
  const extractRootIdentity = await lstat(extractRoot, { bigint: true });
  try {
    const archiveInputRoot = path.join(extractRoot, "input");
    const extractionRoot = path.join(extractRoot, "output");
    await mkdir(archiveInputRoot);
    await mkdir(extractionRoot);
    const archiveInputRootIdentity = await lstat(archiveInputRoot, {
      bigint: true,
    });
    const extractionRootIdentity = await lstat(extractionRoot, {
      bigint: true,
    });
    const privateArchivePath = path.join(archiveInputRoot, "runtime-source.tar.gz");
    const privateArchiveSnapshot = await copyRegularFileExclusiveWithoutLinks(archivePath, privateArchivePath, {
      field: "runtime archive snapshot",
      expectedSourceIdentity: archiveSnapshot.identity,
      expectedSourceParentIdentity: archiveSnapshot.parentIdentity,
      expectedDestinationParentIdentity: archiveInputRootIdentity,
      expectedSha256: normalizeSha256(target.sha256),
    });
    const tarArchivePathArg = toPosixRelativePath(extractionRoot, privateArchivePath);
    preflightTarArchive(tarArchivePathArg, extractionRoot, target.asset, target);
    await requirePinnedFile(
      privateArchivePath,
      privateArchiveSnapshot.destinationIdentity,
      archiveInputRootIdentity,
      privateArchiveSnapshot.sha256,
      "private runtime archive",
    );
    await requireDirectoryIdentity(extractRoot, extractRootIdentity, "runtime extraction work directory");
    await requireDirectoryIdentity(extractionRoot, extractionRootIdentity, "runtime extraction directory");
    console.log(`Extracting ${target.asset} into ${relative(extractionRoot)}`);
    const extract = spawnWithCapturedExecutable("tar", ["-xzf", tarArchivePathArg], {
      cwd: extractionRoot,
      encoding: "utf8",
      env: sanitizedTarEnvironment(),
      stdio: ["ignore", "pipe", "pipe"],
    });
    if (extract.status !== 0) {
      throw new Error(
        `tar failed for ${target.asset}: ${extract.stderr || extract.stdout || `exit ${extract.status}`}`,
      );
    }
    await requirePinnedFile(
      privateArchivePath,
      privateArchiveSnapshot.destinationIdentity,
      archiveInputRootIdentity,
      privateArchiveSnapshot.sha256,
      "private runtime archive",
    );
    await requireDirectoryIdentity(extractRoot, extractRootIdentity, "runtime extraction work directory");
    await requireDirectoryIdentity(extractionRoot, extractionRootIdentity, "runtime extraction directory");

    const archiveRuntimeRoot = await archiveRuntimePath(extractionRoot);
    assertContainedDirectoryTree(archiveRuntimeRoot, "extracted runtime", {
      allowPortableNameCollisions: true,
    });
    const archiveRuntimeIdentity = await lstat(archiveRuntimeRoot, {
      bigint: true,
    });
    const stagingRuntime = await mkdtemp(
      portableTemporaryPathPrefix(`${outputRuntime}.tmp-`, {
        field: "runtime publication temporary prefix",
      }),
    );
    const stagingRuntimeIdentity = await lstat(stagingRuntime, { bigint: true });
    try {
      await cp(archiveRuntimeRoot, stagingRuntime, { dereference: true, force: true, recursive: true });
      await requireDirectoryIdentity(archiveRuntimeRoot, archiveRuntimeIdentity, "extracted runtime root");
      assertContainedDirectoryTree(archiveRuntimeRoot, "extracted runtime", {
        allowPortableNameCollisions: true,
      });
      const prunedFiles = await pruneRuntimeFiles(stagingRuntime, target.prune_files ?? []);
      if (prunedFiles.length > 0) {
        console.log(`Pruned ${prunedFiles.length} runtime file(s): ${prunedFiles.join(", ")}`);
      }
      await verifyRequiredRuntimeFiles(stagingRuntime, target);
      await writeFile(
        path.join(stagingRuntime, runtimeMarkerFile),
        `${JSON.stringify(runtimeMarker(targetName, target), null, 2)}\n`,
      );
      assertContainedDirectoryTree(stagingRuntime, "prepared embedded runtime", {
        allowContainedSymbolicLinks: false,
      });
      await replaceDirectoryTransactionally(stagingRuntime, outputRuntime, {
        expectedDestinationIdentity: outputRuntimeIdentity,
        expectedParentIdentity: outputRuntimeParentIdentity,
        expectedStagingIdentity: stagingRuntimeIdentity,
        field: "embedded Python runtime",
      });
      console.log(`Prepared embedded Python runtime ${target.python} for ${targetName} at ${relative(outputRuntime)}`);
    } finally {
      await removeDirectoryWithoutLinks(stagingRuntime, {
        expectedIdentity: stagingRuntimeIdentity,
        expectedParentIdentity: outputRuntimeParentIdentity,
        field: "temporary embedded runtime staging tree",
        missingOk: true,
      });
    }
  } finally {
    await removeDirectoryWithoutLinks(extractRoot, {
      expectedIdentity: extractRootIdentity,
      field: "temporary runtime extraction tree",
      missingOk: true,
    });
  }
}

function preflightTarArchive(archivePathArgument, workingDirectory, assetName, target) {
  const members = tarListing(["-tzf", archivePathArgument], workingDirectory, assetName);
  const verboseEntries = tarListing(["-tvzf", archivePathArgument], workingDirectory, assetName);
  if (members.length === 0) {
    throw new Error(`runtime archive ${assetName} is empty`);
  }
  if (members.length !== verboseEntries.length) {
    throw new Error(
      `runtime archive ${assetName} has ambiguous member names (${members.length} names, ${verboseEntries.length} records)`,
    );
  }
  const pruneMatchers = (target.prune_files ?? []).map(globPatternToRegExp);
  const portableMembers = members
    .map((member, index) => ({
      isDirectory: verboseEntries[index]?.[0] === "d",
      path: member,
    }))
    .filter((entry) => !runtimeArchiveMemberWillBePruned(entry.path, pruneMatchers));
  validateArchiveMemberSet(portableMembers, `runtime archive ${assetName}`);

  for (let index = 0; index < members.length; index += 1) {
    const member = members[index];
    validateExactArchiveMemberPath(member, `runtime archive ${assetName} member`);
    const verbose = verboseEntries[index];
    const entryType = verbose[0];
    if (entryType === "-" || entryType === "d") {
      continue;
    }
    if (entryType === "l") {
      const marker = " -> ";
      const markerIndex = verbose.lastIndexOf(marker);
      if (markerIndex < 0) {
        throw new Error(`runtime archive ${assetName} has an unreadable symbolic-link record`);
      }
      validateArchiveLinkTarget(member, verbose.slice(markerIndex + marker.length), {
        field: `runtime archive ${assetName} symbolic-link target`,
      });
      continue;
    }
    if (entryType === "h") {
      const marker = " link to ";
      const markerIndex = verbose.lastIndexOf(marker);
      if (markerIndex < 0) {
        throw new Error(`runtime archive ${assetName} has an unreadable hard-link record`);
      }
      validateArchiveLinkTarget(member, verbose.slice(markerIndex + marker.length), {
        field: `runtime archive ${assetName} hard-link target`,
        hardLink: true,
      });
      continue;
    }
    throw new Error(`runtime archive ${assetName} contains unsupported entry type ${entryType || "<empty>"}`);
  }
}

function runtimeArchiveMemberWillBePruned(member, pruneMatchers) {
  if (pruneMatchers.length === 0) {
    return false;
  }
  const normalized = validateExactArchiveMemberPath(member, "runtime archive prune candidate");
  const archiveRoot = String(runtimeSources.archive_root ?? "");
  const rootParts = archiveRoot ? validateExactArchiveMemberPath(archiveRoot, "runtime archive root").split("/") : [];
  const parts = normalized.split("/");
  if (parts.length <= rootParts.length || !rootParts.every((component, index) => parts[index] === component)) {
    return false;
  }
  const relativeParts = parts.slice(rootParts.length);
  for (let length = 1; length <= relativeParts.length; length += 1) {
    const prefix = relativeParts.slice(0, length).join("/");
    if (pruneMatchers.some((matcher) => matcher.test(prefix))) {
      return true;
    }
  }
  return false;
}

function tarListing(argumentsList, workingDirectory, assetName) {
  const listed = spawnWithCapturedExecutable("tar", argumentsList, {
    cwd: workingDirectory,
    encoding: "utf8",
    env: sanitizedTarEnvironment({ LC_ALL: "C" }),
    maxBuffer: 16 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (listed.status !== 0) {
    throw new Error(`tar could not inspect ${assetName}: ${listed.stderr || listed.stdout || `exit ${listed.status}`}`);
  }
  const lines = listed.stdout.split(/\r?\n/u);
  while (lines.at(-1) === "") {
    lines.pop();
  }
  return lines;
}

async function verifyRequiredRuntimeFiles(runtimeRoot, target) {
  for (const requiredFile of target.required_files ?? []) {
    const requiredPath = resolveExactRelativePath(runtimeRoot, requiredFile, "required runtime file");
    try {
      assertRegularFileWithoutLinks(requiredPath, "runtime required file");
    } catch {
      throw new Error(`runtime archive missing required file ${requiredFile}`);
    }
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

async function pruneRuntimeFilesInDirectory(
  runtimeRoot,
  directory,
  matchers,
  prunedFiles,
  expectedDirectoryIdentity = undefined,
) {
  const directoryIdentity = await lstat(directory, { bigint: true });
  if (
    !directoryIdentity.isDirectory() ||
    directoryIdentity.isSymbolicLink() ||
    (expectedDirectoryIdentity !== undefined && !sameFilesystemIdentity(expectedDirectoryIdentity, directoryIdentity))
  ) {
    throw new Error(`runtime prune directory identity changed: ${directory}`);
  }
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    await requireDirectoryIdentity(directory, directoryIdentity, "runtime prune directory");
    const entryPath = resolveExactRelativePath(directory, entry.name, "runtime prune entry");
    const relativePath = toPosixPath(path.relative(runtimeRoot, entryPath));
    const entryIdentity = await lstat(entryPath, { bigint: true });
    if (entryIdentity.isSymbolicLink()) {
      if (matchers.some((matcher) => matcher.test(relativePath))) {
        throw new Error(`runtime prune target must not be a symbolic link: ${relativePath}`);
      }
      continue;
    }
    if (matchers.some((matcher) => matcher.test(relativePath))) {
      if (entryIdentity.isDirectory()) {
        await removeDirectoryWithoutLinks(entryPath, {
          expectedIdentity: entryIdentity,
          expectedParentIdentity: directoryIdentity,
          field: "runtime prune directory",
        });
      } else if (entryIdentity.isFile()) {
        await removeFileWithoutLinks(entryPath, {
          expectedIdentity: entryIdentity,
          expectedParentIdentity: directoryIdentity,
          field: "runtime prune file",
        });
      } else {
        throw new Error(`runtime prune target has an unsupported type: ${relativePath}`);
      }
      prunedFiles.push(relativePath);
      continue;
    }
    if (entryIdentity.isDirectory()) {
      await pruneRuntimeFilesInDirectory(runtimeRoot, entryPath, matchers, prunedFiles, entryIdentity);
    } else if (!entryIdentity.isFile()) {
      throw new Error(`runtime prune tree has an unsupported entry type: ${relativePath}`);
    }
  }
  await requireDirectoryIdentity(directory, directoryIdentity, "runtime prune directory");
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
      console.warn(`Failed to download ${target.asset} from ${url}: ${error.message}`);
    }
  }
  throw new Error(`failed to download ${target.asset} from all configured bases: ${lastError?.message ?? "unknown"}`);
}

async function prepareWheels(targetName, target) {
  const requirements = runtimeSources.wheels?.requirements ?? ["requirements-runtime-core.txt"];
  const bootstrap = runtimeSources.wheels?.bootstrap ?? {};
  const wheelMarker = {
    schema: 2,
    target: targetName,
    release: runtimeSources.release,
    provider: runtimeSources.provider,
    python: target.python,
    triple: target.triple,
    requirements,
    bootstrap,
  };
  if (await markerMatches(path.join(wheelsDir, wheelsMarkerFile), wheelMarker)) {
    try {
      await verifyPreparedWheelhouse(wheelsDir);
      console.log(`Runtime wheels are already prepared at ${relative(wheelsDir)}`);
      return;
    } catch (error) {
      console.warn(`Cached runtime wheelhouse is incomplete and will be rebuilt: ${error.message}`);
    }
  }
  const wheelsDirectoryIdentity = await directoryIdentityIfExists(wheelsDir, "runtime wheelhouse destination");
  const wheelsParentIdentity = await lstat(path.dirname(wheelsDir), {
    bigint: true,
  });

  const preparedRuntimeIdentity = await lstat(outputRuntime, {
    bigint: true,
  });
  if (!preparedRuntimeIdentity.isDirectory() || preparedRuntimeIdentity.isSymbolicLink()) {
    throw new Error("prepared runtime must be a regular non-link directory");
  }
  const python = pythonInPrefix(outputRuntime);
  if (!python) {
    throw new Error(`prepared runtime does not contain a Python executable: ${outputRuntime}`);
  }
  const pythonPin = await pinRegularFile(python, "prepared runtime Python executable");
  await requireDirectoryIdentity(outputRuntime, preparedRuntimeIdentity, "prepared runtime");

  const stagingWheels = await mkdtemp(
    portableTemporaryPathPrefix(`${wheelsDir}.tmp-`, {
      field: "wheel publication temporary prefix",
    }),
  );
  const stagingWheelsIdentity = await lstat(stagingWheels, { bigint: true });
  try {
    const runtimeDirectoryPin = {
      path: outputRuntime,
      identity: preparedRuntimeIdentity,
      field: "prepared runtime",
    };
    const stagingDirectoryPin = {
      path: stagingWheels,
      identity: stagingWheelsIdentity,
      field: "runtime wheelhouse staging directory",
    };
    await prepareBootstrapWheelhouse(stagingWheels, bootstrap, python, pythonPin, [
      runtimeDirectoryPin,
      stagingDirectoryPin,
    ]);

    const requirementsInputRoot = path.join(stagingWheels, ".requirements-inputs");
    await mkdir(requirementsInputRoot);
    const requirementsInputRootIdentity = await lstat(requirementsInputRoot, {
      bigint: true,
    });
    try {
      for (let index = 0; index < requirements.length; index += 1) {
        const requirement = requirements[index];
        const requirementPath = resolveExactRelativePath(repoRoot, requirement, "runtime requirements file");
        const sourcePin = await pinRegularFile(requirementPath, `runtime requirements file ${requirement}`);
        const privateRequirementPath = path.join(requirementsInputRoot, `requirements-${index}.txt`);
        const privateCopy = await copyRegularFileExclusiveWithoutLinks(requirementPath, privateRequirementPath, {
          field: `runtime requirements snapshot ${requirement}`,
          expectedSourceIdentity: sourcePin.identity,
          expectedSourceParentIdentity: sourcePin.parentIdentity,
          expectedDestinationParentIdentity: requirementsInputRootIdentity,
          expectedSha256: sourcePin.sha256,
        });
        const privateRequirementPin = pinFromExclusiveCopy(
          privateRequirementPath,
          privateCopy,
          `private runtime requirements ${requirement}`,
        );
        const env = { ...process.env };
        delete env.PYTHONHOME;
        delete env.PYTHONPATH;
        env.PIP_DISABLE_PIP_VERSION_CHECK = "1";
        const download = await runPinnedCommand(
          python,
          ["-m", "pip", "download", "--dest", stagingWheels, ...pipIndexArgs(), "-r", privateRequirementPath],
          {
            cwd: repoRoot,
            encoding: "utf8",
            stdio: ["ignore", "pipe", "pipe"],
            env,
          },
          {
            files: [pythonPin, sourcePin, privateRequirementPin],
            directories: [
              runtimeDirectoryPin,
              stagingDirectoryPin,
              {
                path: requirementsInputRoot,
                identity: requirementsInputRootIdentity,
                field: "runtime requirements snapshot directory",
              },
            ],
          },
        );
        if (download.status !== 0) {
          throw new Error(
            `pip download failed for ${requirement}: ${
              download.stderr || download.stdout || `exit ${download.status}`
            }`,
          );
        }
      }
    } finally {
      await removeDirectoryWithoutLinks(requirementsInputRoot, {
        expectedIdentity: requirementsInputRootIdentity,
        expectedParentIdentity: stagingWheelsIdentity,
        field: "runtime requirements snapshot directory",
        missingOk: true,
      });
    }
    await buildSourceArchivesIntoWheels(stagingWheels, python, pythonPin, [runtimeDirectoryPin, stagingDirectoryPin]);
    await requirePinnedFilePin(pythonPin);
    await requireDirectoryIdentity(outputRuntime, preparedRuntimeIdentity, "prepared runtime");
    await assertNoSourceArchives(stagingWheels);
    await writeFile(path.join(stagingWheels, wheelsMarkerFile), `${JSON.stringify(wheelMarker, null, 2)}\n`, {
      flag: "wx",
    });
    await verifyPreparedWheelhouse(stagingWheels);
    await replaceDirectoryTransactionally(stagingWheels, wheelsDir, {
      expectedDestinationIdentity: wheelsDirectoryIdentity,
      expectedParentIdentity: wheelsParentIdentity,
      expectedStagingIdentity: stagingWheelsIdentity,
      field: "runtime wheelhouse",
    });
    console.log(`Prepared runtime wheels for ${targetName} at ${relative(wheelsDir)}`);
  } finally {
    await removeDirectoryWithoutLinks(stagingWheels, {
      expectedIdentity: stagingWheelsIdentity,
      expectedParentIdentity: wheelsParentIdentity,
      field: "temporary runtime wheelhouse staging tree",
      missingOk: true,
    });
  }
}

async function prepareBootstrapWheelhouse(stagingWheels, bootstrap, python, pythonPin, directoryPins) {
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
  const download = await runPinnedCommand(
    python,
    ["-m", "pip", "download", "--dest", stagingWheels, ...pipIndexArgs(), ...packages],
    {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      env,
    },
    {
      files: [pythonPin],
      directories: directoryPins,
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

async function buildSourceArchivesIntoWheels(stagingWheels, python, pythonPin, directoryPins) {
  const sourceArchives = await listSourceArchives(stagingWheels);
  if (sourceArchives.length === 0) {
    return;
  }
  const env = { ...process.env };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  env.PIP_DISABLE_PIP_VERSION_CHECK = "1";
  for (const archivePath of sourceArchives) {
    const archivePin = await pinRegularFile(archivePath, "runtime source archive");
    const build = await runPinnedCommand(
      python,
      ["-m", "pip", "wheel", "--wheel-dir", stagingWheels, "--no-deps", ...pipIndexArgs(), archivePath],
      {
        cwd: repoRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
        env,
      },
      {
        files: [pythonPin, archivePin],
        directories: directoryPins,
      },
    );
    if (build.status !== 0) {
      throw new Error(
        `pip wheel failed for source archive ${path.basename(archivePath)}: ${
          build.stderr || build.stdout || `exit ${build.status}`
        }`,
      );
    }
    await removeFileWithoutLinks(archivePath, {
      expectedIdentity: archivePin.identity,
      expectedParentIdentity: archivePin.parentIdentity,
      field: "built source archive",
    });
    console.log(`Built wheel from source archive ${path.basename(archivePath)}`);
  }
}

async function verifyWheelhouse(targetName) {
  const preparedRuntimeIdentity = await lstat(outputRuntime, {
    bigint: true,
  });
  const wheelhouseIdentity = await lstat(wheelsDir, { bigint: true });
  const wheelhouseParentIdentity = await lstat(path.dirname(wheelsDir), {
    bigint: true,
  });
  const python = pythonInPrefix(outputRuntime);
  if (!python) {
    throw new Error(`prepared runtime does not contain a Python executable: ${outputRuntime}`);
  }
  const pythonPin = await pinRegularFile(python, "prepared runtime Python executable");
  await requireDirectoryIdentity(outputRuntime, preparedRuntimeIdentity, "prepared runtime");
  await requireDirectoryIdentity(wheelsDir, wheelhouseIdentity, "runtime wheelhouse");
  await assertNoSourceArchives(wheelsDir);
  const requirements = runtimeSources.wheels?.requirements ?? ["requirements-runtime-core.txt"];
  const verificationRoot = await mkdtemp(path.join(path.dirname(wheelsDir), ".runtime-wheel-verify-"));
  const verificationRootIdentity = await lstat(verificationRoot, {
    bigint: true,
  });
  try {
    for (let index = 0; index < requirements.length; index += 1) {
      const requirement = requirements[index];
      const requirementPath = resolveExactRelativePath(repoRoot, requirement, "runtime requirements file");
      const sourcePin = await pinRegularFile(requirementPath, `runtime requirements file ${requirement}`);
      const privateRequirementPath = path.join(verificationRoot, `requirements-${index}.txt`);
      const privateCopy = await copyRegularFileExclusiveWithoutLinks(requirementPath, privateRequirementPath, {
        field: `runtime verification requirements snapshot ${requirement}`,
        expectedSourceIdentity: sourcePin.identity,
        expectedSourceParentIdentity: sourcePin.parentIdentity,
        expectedDestinationParentIdentity: verificationRootIdentity,
        expectedSha256: sourcePin.sha256,
      });
      const verify = await runPinnedCommand(
        python,
        ["-m", "pip", "install", "--dry-run", "--no-index", "--find-links", wheelsDir, "-r", privateRequirementPath],
        {
          cwd: repoRoot,
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
        },
        {
          files: [
            pythonPin,
            sourcePin,
            pinFromExclusiveCopy(
              privateRequirementPath,
              privateCopy,
              `private runtime verification requirements ${requirement}`,
            ),
          ],
          directories: [
            {
              path: outputRuntime,
              identity: preparedRuntimeIdentity,
              field: "prepared runtime",
            },
            {
              path: wheelsDir,
              identity: wheelhouseIdentity,
              field: "runtime wheelhouse",
            },
            {
              path: verificationRoot,
              identity: verificationRootIdentity,
              field: "runtime wheel verification directory",
            },
          ],
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
  } finally {
    await removeDirectoryWithoutLinks(verificationRoot, {
      expectedIdentity: verificationRootIdentity,
      expectedParentIdentity: wheelhouseParentIdentity,
      field: "runtime wheel verification directory",
      missingOk: true,
    });
  }
  await requirePinnedFilePin(pythonPin);
  await requireDirectoryIdentity(outputRuntime, preparedRuntimeIdentity, "prepared runtime");
  await requireDirectoryIdentity(wheelsDir, wheelhouseIdentity, "runtime wheelhouse");
  await verifyPreparedWheelhouse(wheelsDir);
  console.log(`Verified offline runtime wheels for ${targetName}`);
}

async function assertNoSourceArchives(directory) {
  const archives = await listSourceArchives(directory);
  if (archives.length > 0) {
    throw new Error(
      `runtime wheelhouse must not contain source archives: ${archives
        .map((archivePath) => path.basename(archivePath))
        .join(", ")}`,
    );
  }
}

async function verifyPreparedWheelhouse(directory) {
  const directoryIdentity = await lstat(directory, { bigint: true });
  if (!directoryIdentity.isDirectory() || directoryIdentity.isSymbolicLink()) {
    throw new Error("runtime wheelhouse must be a regular non-link directory");
  }
  assertContainedDirectoryTree(directory, "runtime wheelhouse", {
    allowContainedSymbolicLinks: false,
  });
  await assertNoSourceArchives(directory);
  const entries = await readdir(directory, { withFileTypes: true });
  const wheelEntries = entries.filter((entry) => entry.name.toLowerCase().endsWith(".whl"));
  if (wheelEntries.length === 0) {
    throw new Error("runtime wheelhouse does not contain any wheel files");
  }
  for (const entry of wheelEntries) {
    assertRegularFileWithoutLinks(
      resolveExactRelativePath(directory, entry.name, "runtime wheelhouse entry"),
      "runtime wheelhouse wheel",
    );
  }
  assertRegularFileWithoutLinks(path.join(directory, wheelsMarkerFile), "runtime wheelhouse marker");
  assertContainedDirectoryTree(directory, "runtime wheelhouse", {
    allowContainedSymbolicLinks: false,
  });
  await requireDirectoryIdentity(directory, directoryIdentity, "runtime wheelhouse");
}

async function listSourceArchives(directory) {
  const directoryIdentity = await directoryIdentityIfExists(directory, "runtime wheelhouse");
  if (directoryIdentity === null) {
    return [];
  }
  const entries = await readdir(directory);
  const archives = entries
    .filter((entry) => sourceArchiveSuffixes.some((suffix) => entry.toLowerCase().endsWith(suffix)))
    .map((entry) => resolveExactRelativePath(directory, entry, "runtime source archive"));
  for (const archive of archives) {
    assertRegularFileWithoutLinks(archive, "runtime source archive");
  }
  await requireDirectoryIdentity(directory, directoryIdentity, "runtime wheelhouse");
  return archives;
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
  const extractRootIdentity = await lstat(extractRoot, { bigint: true });
  if (!extractRootIdentity.isDirectory() || extractRootIdentity.isSymbolicLink()) {
    throw new Error("runtime extraction root must be a regular non-link directory");
  }
  const configured = runtimeSources.archive_root;
  if (configured) {
    const candidate = resolveExactRelativePath(extractRoot, configured, "runtime archive root");
    const candidateIdentity = await directoryIdentityIfExists(candidate, "runtime archive root");
    if (candidateIdentity !== null) {
      await requireDirectoryIdentity(extractRoot, extractRootIdentity, "runtime extraction root");
      await requireDirectoryIdentity(candidate, candidateIdentity, "runtime archive root");
      return candidate;
    }
  }
  const entries = await readdir(extractRoot, { withFileTypes: true });
  const directories = [];
  for (const entry of entries) {
    const candidate = resolveExactRelativePath(extractRoot, entry.name, "runtime extraction entry");
    const metadata = await lstat(candidate, { bigint: true });
    if (metadata.isSymbolicLink()) {
      continue;
    }
    if (metadata.isDirectory()) {
      directories.push({ name: entry.name, identity: metadata });
    }
  }
  await requireDirectoryIdentity(extractRoot, extractRootIdentity, "runtime extraction root");
  if (directories.length === 1) {
    const candidate = resolveExactRelativePath(extractRoot, directories[0].name, "runtime archive root");
    await requireDirectoryIdentity(candidate, directories[0].identity, "runtime archive root");
    return candidate;
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
  return candidates.find((candidate) => {
    try {
      assertRegularFileWithoutLinks(candidate, "embedded runtime Python");
      return true;
    } catch {
      return false;
    }
  });
}

async function downloadFile(url, outputPath) {
  const outputDirectory = assertSafeMutableDirectory(path.dirname(outputPath), {
    field: "download output directory",
  });
  await mkdir(outputDirectory, { recursive: true });
  assertSafeMutableDirectory(outputDirectory, {
    field: "download output directory",
  });
  const outputDirectoryIdentity = await lstat(outputDirectory, {
    bigint: true,
  });
  const outputIdentity = await fileIdentityIfExists(outputPath, "download destination file");
  const privateDownloadRoot = await mkdtemp(path.join(outputDirectory, ".runtime-download-"));
  const privateDownloadRootIdentity = await lstat(privateDownloadRoot, {
    bigint: true,
  });
  let privatePath = path.join(privateDownloadRoot, "payload-curl");
  const tempPath = portableSiblingPath(
    outputPath,
    `.download-${randomUUID()}`,
    "temporary runtime download publication file",
  );
  let tempPathIdentity = null;
  try {
    try {
      await downloadFileWithCurl(url, privatePath);
    } catch (error) {
      if (!isMissingCommandError(error)) {
        throw error;
      }
      privatePath = path.join(privateDownloadRoot, "payload-node");
      await downloadFileWithNodeHttps(url, privatePath);
    }
    assertRegularFileWithoutLinks(privatePath, "private downloaded runtime file");
    const privateDownloadMetadata = await lstat(privatePath, { bigint: true });
    // Publish the sibling staging name with create-if-absent semantics.
    // A normal rename would silently overwrite an unrelated path in the
    // astronomically unlikely event of a UUID collision or concurrent reuse.
    const currentOutputDirectoryIdentity = await lstat(outputDirectory, {
      bigint: true,
    });
    if (!sameFilesystemIdentity(outputDirectoryIdentity, currentOutputDirectoryIdentity)) {
      throw new Error("download output directory identity changed");
    }
    await link(privatePath, tempPath);
    tempPathIdentity = privateDownloadMetadata;
    const publicationMetadata = await lstat(tempPath, { bigint: true });
    if (
      privateDownloadMetadata.dev !== publicationMetadata.dev ||
      privateDownloadMetadata.ino !== publicationMetadata.ino
    ) {
      throw new Error("private runtime download identity changed before publication");
    }
    await removeFileWithoutLinks(privatePath, {
      expectedIdentity: privateDownloadMetadata,
      expectedParentIdentity: privateDownloadRootIdentity,
      field: "private runtime download source",
    });
    await replaceFileTransactionally(tempPath, outputPath, {
      expectedDestinationIdentity: outputIdentity,
      expectedParentIdentity: outputDirectoryIdentity,
      expectedStagingIdentity: tempPathIdentity,
      field: "downloaded runtime file",
    });
  } finally {
    if (tempPathIdentity !== null) {
      await removeFileWithoutLinks(tempPath, {
        expectedIdentity: tempPathIdentity,
        expectedParentIdentity: outputDirectoryIdentity,
        field: "temporary runtime download publication file",
        missingOk: true,
      });
    }
    await removeDirectoryWithoutLinks(privateDownloadRoot, {
      expectedIdentity: privateDownloadRootIdentity,
      expectedParentIdentity: outputDirectoryIdentity,
      field: "private runtime download directory",
      missingOk: true,
    });
  }
}

async function downloadFileWithCurl(url, outputPath) {
  const timeoutSeconds = process.env.SHINSEKAI_DOWNLOAD_TIMEOUT_SECONDS ?? "900";
  const curlEnvironment = capturedCurlEnvironment();
  const download = spawnWithCapturedExecutable(
    "curl",
    [
      "--disable",
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
      cwd: path.dirname(outputPath),
      env: curlEnvironment.env,
      stdio: ["ignore", "inherit", "inherit"],
    },
    {
      requiredDirectories: curlEnvironment.directories,
      requiredFiles: curlEnvironment.files,
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
      const file = createWriteStream(outputPath, { flags: "wx" });
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

async function fileIdentityIfExists(target, field) {
  try {
    const metadata = await lstat(target, { bigint: true });
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      throw new Error(`${field} must be a regular non-link file`);
    }
    return metadata;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return null;
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

async function fileSha256Matches(target, expected) {
  if (!expected) {
    return false;
  }
  try {
    return (
      (
        await sha256RegularFileWithoutLinks(target, {
          field: "sha256 source file",
        })
      ).sha256 === normalizeSha256(expected)
    );
  } catch {
    return false;
  }
}

async function assertFileSha256(target, expected) {
  const normalizedExpected = normalizeSha256(expected);
  try {
    return await sha256RegularFileWithoutLinks(target, {
      field: "sha256 source file",
      expectedSha256: normalizedExpected,
    });
  } catch (error) {
    throw new Error(`sha256 mismatch for ${target}: expected ${normalizedExpected}: ${error.message}`);
  }
}

async function pinRegularFile(target, field) {
  const snapshot = await sha256RegularFileWithoutLinks(target, {
    field,
  });
  return {
    path: target,
    field,
    identity: snapshot.identity,
    parentIdentity: snapshot.parentIdentity,
    sha256: snapshot.sha256,
  };
}

function pinFromExclusiveCopy(target, snapshot, field) {
  return {
    path: target,
    field,
    identity: snapshot.destinationIdentity,
    parentIdentity: snapshot.destinationParentIdentity,
    sha256: snapshot.sha256,
  };
}

async function requirePinnedFilePin(pin) {
  return requirePinnedFile(pin.path, pin.identity, pin.parentIdentity, pin.sha256, pin.field);
}

async function requirePinnedState(files, directories) {
  for (const directory of directories) {
    await requireDirectoryIdentity(directory.path, directory.identity, directory.field);
  }
  for (const file of files) {
    await requirePinnedFilePin(file);
  }
}

async function runPinnedCommand(command, argumentsList, options, { files = [], directories = [] } = {}) {
  await requirePinnedState(files, directories);
  const result = spawnWithCapturedExecutable(command, argumentsList, options);
  await requirePinnedState(files, directories);
  return result;
}

function spawnWithCapturedExecutable(
  command,
  argumentsList,
  options,
  { requiredFiles = [], requiredDirectories = [] } = {},
) {
  requireExternalPathSnapshots(requiredFiles, requiredDirectories);
  const executable = captureExecutableSnapshot(command, {
    field: `external command ${JSON.stringify(command)}`,
  });
  const executablePath = requireExecutableSnapshot(executable, `external command ${JSON.stringify(command)}`);
  let result;
  try {
    result = spawnSync(executablePath, argumentsList, options);
  } finally {
    requireExecutableSnapshot(executable, `external command ${JSON.stringify(command)}`);
    requireExternalPathSnapshots(requiredFiles, requiredDirectories);
  }
  return result;
}

function requireExternalPathSnapshots(files, directories) {
  for (const file of files) {
    requireRegularFileSnapshot(file.snapshot, file.field);
  }
  for (const directory of directories) {
    requireDirectorySnapshot(directory.snapshot, directory.field);
  }
}

function capturedCurlEnvironment() {
  const env = { ...process.env };
  const files = [];
  const directories = [];
  for (const name of ["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"]) {
    if (!Object.prototype.hasOwnProperty.call(env, name)) {
      continue;
    }
    const field = `${name} environment file`;
    const snapshot = captureRegularFileAliasSnapshot(env[name] ?? "", field);
    env[name] = snapshot.path;
    files.push({ field, snapshot });
  }
  if (Object.prototype.hasOwnProperty.call(env, "SSL_CERT_DIR")) {
    const field = "SSL_CERT_DIR environment directory";
    const snapshot = captureDirectoryAliasSnapshot(env.SSL_CERT_DIR ?? "", field);
    env.SSL_CERT_DIR = snapshot.path;
    directories.push({ field, snapshot });
  }
  return { directories, env, files };
}

function sanitizedTarEnvironment(overrides = {}) {
  const env = { ...process.env, ...overrides };
  delete env.TAR_OPTIONS;
  delete env.TAPE;
  return env;
}

async function requirePinnedFile(target, expectedIdentity, expectedParentIdentity, expectedSha256, field) {
  return sha256RegularFileWithoutLinks(target, {
    field,
    expectedIdentity,
    expectedParentIdentity,
    expectedSha256,
  });
}

async function requireDirectoryIdentity(target, expectedIdentity, field) {
  const metadata = await lstat(target, { bigint: true });
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || !sameFilesystemIdentity(expectedIdentity, metadata)) {
    throw new Error(`${field} identity changed`);
  }
  return metadata;
}

async function markerMatches(markerPath, expected) {
  try {
    const actual = JSON.parse(
      (
        await readRegularFileWithoutLinks(markerPath, {
          field: "runtime marker file",
          encoding: "utf8",
        })
      ).data,
    );
    return JSON.stringify(actual) === JSON.stringify(expected);
  } catch {
    return false;
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
