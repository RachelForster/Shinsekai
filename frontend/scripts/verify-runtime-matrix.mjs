import path from "node:path";
import { fileURLToPath } from "node:url";
import { readRegularFileWithoutLinks } from "./path-contract.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");

const runtimeSourcesPath = path.join(frontendDir, "src-tauri", "runtime_sources.json");
const workflowPath = path.join(repoRoot, ".github", "workflows", "tauri-desktop.yml");
const releaseWorkflowPath = path.join(repoRoot, ".github", "workflows", "release.yml");
const packageJsonPath = path.join(frontendDir, "package.json");
const srcTauriCargoTomlPath = path.join(frontendDir, "src-tauri", "Cargo.toml");
const tauriConfigPath = path.join(frontendDir, "src-tauri", "tauri.conf.json");
const prepareRuntimeScriptPath = path.join(frontendDir, "scripts", "prepare-runtime.mjs");
const prepareTauriResourcesScriptPath = path.join(frontendDir, "scripts", "prepare-tauri-resources.mjs");
const verifyTauriResourcesScriptPath = path.join(frontendDir, "scripts", "verify-tauri-resources.mjs");
const verifyPackagedRuntimeScriptPath = path.join(frontendDir, "scripts", "verify-packaged-runtime.mjs");
const pathContractScriptPath = path.join(frontendDir, "scripts", "path-contract.mjs");
const tauriResourcePlanScriptPath = path.join(frontendDir, "scripts", "tauri-resource-plan.mjs");
const rustToolchainPath = path.join(repoRoot, "rust-toolchain.toml");

const expectedRustToolchain = "1.96.0";
const expectedTargets = ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64", "macos-arm64"];
const linuxTriples = new Map([
  ["linux-x64", "x86_64-unknown-linux-gnu"],
  ["linux-arm64", "aarch64-unknown-linux-gnu"],
]);
const portableRuntimePruneDirectories = ["share/terminfo"];
const linuxRuntimePruneFiles = ["lib/python*/lib-dynload/_tkinter.*.so", ...portableRuntimePruneDirectories];
const windowsRequiredFiles = new Map([
  ["windows-x64", ["python.exe", "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll"]],
  ["windows-arm64", ["python.exe", "vcruntime140.dll", "vcruntime140_1.dll"]],
]);
const expectedBundles = new Map([
  ["linux-x64", ["deb"]],
  ["linux-arm64", ["deb"]],
  ["windows-x64", ["nsis"]],
  ["windows-arm64", ["none"]],
  ["macos-arm64", ["dmg"]],
]);
const expectedArtifactPaths = [
  "frontend/src-tauri/target/release/bundle/appimage/*.AppImage",
  "frontend/src-tauri/target/release/bundle/deb/*.deb",
  "frontend/src-tauri/target/release/bundle/dmg/*.dmg",
  "frontend/src-tauri/target/release/bundle/msi/*.msi",
  "frontend/src-tauri/target/release/bundle/nsis/*.exe",
  "frontend/src-tauri/target/release/bundle/rpm/*.rpm",
];

const runtimeSources = JSON.parse(await readStrictText(runtimeSourcesPath, "runtime source manifest"));
const workflow = await readStrictText(workflowPath, "Tauri build workflow");
const releaseWorkflow = await readStrictText(releaseWorkflowPath, "release workflow");
const packageJson = JSON.parse(await readStrictText(packageJsonPath, "frontend package manifest"));
const srcTauriCargoToml = await readStrictText(srcTauriCargoTomlPath, "Tauri Cargo manifest");
const tauriConfig = JSON.parse(await readStrictText(tauriConfigPath, "Tauri configuration"));
const prepareRuntimeScript = await readStrictText(prepareRuntimeScriptPath, "runtime preparation script");
const prepareTauriResourcesScript = await readStrictText(
  prepareTauriResourcesScriptPath,
  "Tauri resource preparation script",
);
const verifyTauriResourcesScript = await readStrictText(
  verifyTauriResourcesScriptPath,
  "Tauri resource verification script",
);
const verifyPackagedRuntimeScript = await readStrictText(
  verifyPackagedRuntimeScriptPath,
  "packaged runtime verification script",
);
const pathContractScript = await readStrictText(pathContractScriptPath, "build path contract");
const tauriResourcePlanScript = await readStrictText(tauriResourcePlanScriptPath, "Tauri resource source plan");
const rustToolchainConfig = await readStrictText(rustToolchainPath, "Rust toolchain configuration");

const errors = [];

check(runtimeSources.provider === "python-build-standalone", "runtime provider must be python-build-standalone");
check(runtimeSources.release === "20260602", "runtime release must stay pinned to PBS 20260602");
check(runtimeSources.archive_root === "python", "runtime archive_root must match PBS install_only archive layout");
check(
  Array.isArray(runtimeSources.base_urls) && runtimeSources.base_urls.length > 0,
  "runtime base_urls must not be empty",
);

const sourceTargets = Object.keys(runtimeSources.targets ?? {}).sort();
check(
  sameList(sourceTargets, [...expectedTargets].sort()),
  `runtime_sources targets must be exactly ${expectedTargets.join(", ")}`,
);

const workflowTargets = [...workflow.matchAll(/^\s+- platform:\s*([^\s#]+)/gm)].map((match) => match[1]).sort();
check(
  sameList(workflowTargets, [...expectedTargets].sort()),
  `workflow build matrix must cover ${expectedTargets.join(", ")}`,
);
check(
  sameList(sourceTargets, workflowTargets),
  `runtime_sources targets (${sourceTargets.join(", ")}) must match workflow targets (${workflowTargets.join(", ")})`,
);

const workflowMatrix = workflowBuildMatrix();
for (const targetName of expectedTargets) {
  const expectedTargetBundles = expectedBundles.get(targetName) ?? [];
  const actualBundles = splitBundles(workflowMatrix.get(targetName)?.bundles ?? "");
  check(
    sameList([...actualBundles].sort(), [...expectedTargetBundles].sort()),
    `${targetName} workflow bundles must be ${expectedTargetBundles.join(",")}`,
  );
}
check(
  workflow.includes("if-no-files-found: error"),
  "artifact upload must fail when expected installer files are missing",
);
for (const artifactPath of expectedArtifactPaths) {
  check(workflow.includes(artifactPath), `artifact upload path must include ${artifactPath}`);
}

for (const targetName of expectedTargets) {
  const target = runtimeSources.targets?.[targetName];
  if (!target) {
    continue;
  }
  check(Boolean(target.python), `${targetName} must pin a Python version`);
  check(Boolean(target.triple), `${targetName} must pin a PBS target triple`);
  check(Boolean(target.asset), `${targetName} must pin a PBS archive asset`);
  check(Boolean(target.sha256), `${targetName} must pin a sha256 digest`);
  check(
    Array.isArray(target.required_files) && target.required_files.length > 0,
    `${targetName} must list required files`,
  );
  check(
    target.asset.includes(`${target.python}+${runtimeSources.release}`),
    `${targetName} asset must match pinned Python/release`,
  );
  check(target.asset.includes(target.triple), `${targetName} asset must match pinned triple`);
  check(
    target.asset.includes("install_only_stripped.tar.gz"),
    `${targetName} must use stripped install_only PBS archive`,
  );

  if (targetName.startsWith("linux-")) {
    check(target.triple === linuxTriples.get(targetName), `${targetName} must use the expected gnu triple`);
    check(!target.triple.includes("musl"), `${targetName} must not use musl PBS builds`);
    check(!target.asset.includes("static"), `${targetName} must not use static PBS builds`);
    check(
      target.required_files.includes("bin/python3.10"),
      `${targetName} must include the PBS Python 3.10 executable`,
    );
    check(
      sameList(target.prune_files ?? [], linuxRuntimePruneFiles),
      `${targetName} must prune unused Tk and non-portable terminfo runtime files`,
    );
  }

  if (targetName.startsWith("macos-")) {
    check(target.python.startsWith("3.10."), `${targetName} should stay on Python 3.10`);
    check(
      target.required_files.includes("bin/python3.10"),
      `${targetName} must include the PBS Python 3.10 executable`,
    );
    check(
      sameList(target.prune_files ?? [], portableRuntimePruneDirectories),
      `${targetName} must prune non-portable terminfo runtime files`,
    );
  }

  if (targetName === "windows-x64") {
    check(target.python.startsWith("3.10."), "windows-x64 should stay on Python 3.10");
  }

  if (targetName === "windows-arm64") {
    check(
      target.python === "3.11.15",
      "windows-arm64 must explicitly use the documented PBS 3.11 fallback until a 3.10 asset exists",
    );
    check(
      !(target.required_files ?? []).includes("vcruntime140_threads.dll"),
      "windows-arm64 PBS archive must not require vcruntime140_threads.dll because that asset does not include it",
    );
  }

  if (targetName.startsWith("windows-")) {
    for (const requiredFile of windowsRequiredFiles.get(targetName) ?? []) {
      check(target.required_files.includes(requiredFile), `${targetName} must require ${requiredFile}`);
    }
  }
}

check(
  packageJson.scripts?.["prepare:runtime"] === "node scripts/prepare-runtime.mjs",
  "package script prepare:runtime must run prepare-runtime.mjs",
);
check(
  packageJson.scripts?.["prepare:tauri-resources"] === "node scripts/prepare-tauri-resources.mjs",
  "package script prepare:tauri-resources must run prepare-tauri-resources.mjs",
);
check(
  packageJson.scripts?.["verify:tauri-resources"] === "node scripts/verify-tauri-resources.mjs",
  "package script verify:tauri-resources must run verify-tauri-resources.mjs",
);
check(
  packageJson.scripts?.["verify:packaged-runtime"] === "node scripts/verify-packaged-runtime.mjs",
  "package script verify:packaged-runtime must run verify-packaged-runtime.mjs",
);
check(
  packageJson.scripts?.["verify:runtime-matrix"] === "node scripts/verify-runtime-matrix.mjs",
  "package script verify:runtime-matrix must run verify-runtime-matrix.mjs",
);

const beforeBuildCommand = tauriConfig.build?.beforeBuildCommand ?? "";
for (const command of [
  "pnpm prepare:runtime --verify --skip-wheels",
  "pnpm prepare:tauri-resources",
  "pnpm verify:tauri-resources",
]) {
  check(beforeBuildCommand.includes(command), `Tauri beforeBuildCommand must include ${command}`);
}
check(tauriConfig.bundle?.resources?.["resources/"] === "", "Tauri bundle must include the staged resources directory");
check(
  tauriConfig.app?.macOSPrivateApi === true,
  "Tauri app config must enable macOSPrivateApi for transparent desktop chat windows",
);
check(
  /tauri\s*=\s*\{[^}]*features\s*=\s*\[[^\]]*"macos-private-api"/s.test(srcTauriCargoToml),
  "src-tauri Cargo.toml must enable the tauri macos-private-api feature",
);
check(
  rustToolchainConfig.includes(`channel = "${expectedRustToolchain}"`) &&
    rustToolchainConfig.includes('profile = "minimal"'),
  `rust-toolchain.toml must pin Rust ${expectedRustToolchain} with the minimal profile`,
);
check(
  workflow.includes(`dtolnay/rust-toolchain@${expectedRustToolchain}`) &&
    releaseWorkflow.includes(`dtolnay/rust-toolchain@${expectedRustToolchain}`),
  `desktop and release workflows must use Rust ${expectedRustToolchain}`,
);
check(
  !workflow.includes("mozilla-actions/sccache-action") &&
    !releaseWorkflow.includes("mozilla-actions/sccache-action") &&
    !workflow.includes("RUSTC_WRAPPER=sccache") &&
    !releaseWorkflow.includes("RUSTC_WRAPPER=sccache"),
  "desktop and release workflows must rely on rust-cache target reuse instead of sccache",
);
check(
  workflow.includes("shared-key: build") && releaseWorkflow.includes("shared-key: build"),
  "desktop and release workflows must share the platform-isolated Rust build cache",
);
check(
  !workflow.includes("choco install nsis") && !releaseWorkflow.includes("choco install nsis"),
  "Tauri workflows must use tauri-bundler's pinned NSIS toolchain instead of installing an unused system copy",
);
check(!workflow.includes("needs: runtime-gate"), "desktop build matrix must run in parallel with runtime-gate");
check(
  workflow.includes("pnpm prepare:runtime --target ${{ matrix.platform }} --verify --skip-wheels") &&
    releaseWorkflow.includes("pnpm prepare:runtime --target ${{ matrix.platform }} --verify --skip-wheels"),
  "desktop and release workflows must prepare the target-specific embedded runtime without packaged wheels",
);
check(
  workflow.includes("actions/cache/restore@v4") &&
    workflow.includes("actions/cache/save@v4") &&
    workflow.includes("embedded-python-runtime-${{ runner.os }}-${{ matrix.platform }}"),
  "workflow build job must cache embedded Python runtime per target",
);
check(
  !workflow.includes("\n            wheels\n") && !releaseWorkflow.includes("\n            wheels\n"),
  "embedded Python runtime cache must not include a packaged wheels directory",
);
check(
  workflow.includes(
    "pnpm verify:packaged-runtime --target ${{ matrix.platform }} --require-installers --installer-bundles ${{ matrix.bundles }}",
  ),
  "workflow build job must verify the packaged embedded runtime and selected installer artifacts after packaging",
);
check(
  releaseWorkflow.includes("Clear stale Tauri bundle outputs") &&
    releaseWorkflow.includes("rm -rf src-tauri/target/release/bundle"),
  "release workflow must clear stale Tauri bundle outputs before packaging",
);
check(
  !releaseWorkflow.includes("find frontend/src-tauri/target/release/bundle -type f") &&
    releaseWorkflow.includes('collect_required "frontend/src-tauri/target/release/bundle/appimage/*.AppImage"') &&
    releaseWorkflow.includes('collect_required "frontend/src-tauri/target/release/bundle/deb/*.deb"') &&
    releaseWorkflow.includes('collect_required "frontend/src-tauri/target/release/bundle/nsis/*.exe"') &&
    releaseWorkflow.includes('collect_required "frontend/src-tauri/target/release/bundle/dmg/*.dmg"') &&
    releaseWorkflow.includes('collect_required "frontend/src-tauri/target/release/bundle/macos/*.app.tar.gz"'),
  "release workflow must collect assets from platform-specific bundle directories only",
);
check(
  workflow.includes('if [[ "${{ matrix.bundles }}" == "none" ]]; then') &&
    workflow.includes("pnpm tauri build --ci --no-bundle") &&
    workflow.includes("pnpm tauri build --ci --bundles ${{ matrix.bundles }}") &&
    workflow.includes("pnpm verify:packaged-runtime --target ${{ matrix.platform }}") &&
    workflow.includes("if: matrix.bundles != 'none'"),
  "workflow must skip installer generation and artifact upload for no-bundle platforms",
);
check(!workflow.includes("pnpm tauri build -v"), "workflow must not use verbose Tauri build logging in CI");
check(
  !prepareRuntimeScript.includes('["-xzf", archivePath, "-C", extractRoot]'),
  "prepare-runtime must not pass an absolute archivePath directly to tar on Windows",
);
check(
  prepareRuntimeScript.includes("toPosixRelativePath(extractionRoot, privateArchivePath)") &&
    prepareRuntimeScript.includes("cwd: extractionRoot") &&
    prepareRuntimeScript.includes("copyRegularFileExclusiveWithoutLinks(") &&
    prepareRuntimeScript.includes("privateArchiveSnapshot.destinationIdentity"),
  "prepare-runtime must extract an identity-bound private archive through a relative path",
);
check(
  prepareRuntimeScript.includes("preflightTarArchive(tarArchivePathArg, extractionRoot, target.asset, target)") &&
    prepareRuntimeScript.indexOf("preflightTarArchive(tarArchivePathArg, extractionRoot, target.asset, target)") <
      prepareRuntimeScript.indexOf('spawnWithCapturedExecutable("tar", ["-xzf", tarArchivePathArg]'),
  "prepare-runtime must validate every tar member and link before extraction",
);
check(
  prepareRuntimeScript.includes("runtimeArchiveMemberWillBePruned") &&
    prepareRuntimeScript.includes("allowPortableNameCollisions: true") &&
    prepareRuntimeScript.indexOf("pruneRuntimeFiles(stagingRuntime") <
      prepareRuntimeScript.indexOf('assertContainedDirectoryTree(stagingRuntime, "prepared embedded runtime"'),
  "prepare-runtime may defer native filename-collision checks only until the explicit prune step",
);
check(
  pathContractScript.includes("export function resolveAbsoluteEnvironmentPath") &&
    pathContractScript.includes("export function captureExecutableSnapshot") &&
    pathContractScript.includes("export function requireExecutableSnapshot") &&
    pathContractScript.includes("export function validateExactArchiveMemberPath") &&
    pathContractScript.includes("export function validateArchiveLinkTarget") &&
    pathContractScript.includes("export async function removeDirectoryWithoutLinks") &&
    pathContractScript.includes("export async function removeFileWithoutLinks") &&
    pathContractScript.includes("export async function replaceDirectoryTransactionally") &&
    pathContractScript.includes("sameFilesystemIdentity"),
  "build scripts must retain the shared environment and archive path contract",
);
check(
  prepareRuntimeScript.includes('spawnWithCapturedExecutable("tar"') &&
    prepareRuntimeScript.includes("spawnWithCapturedExecutable(command, argumentsList, options)") &&
    prepareRuntimeScript.includes("spawnSync(executablePath, argumentsList, options)") &&
    verifyPackagedRuntimeScript.includes("captureExecutableSnapshot(command") &&
    verifyPackagedRuntimeScript.includes("spawnSync(executablePath, privateArgs") &&
    verifyPackagedRuntimeScript.includes("requireExecutableSnapshot(executable"),
  "build and package inspection tools must execute one identity-bound absolute executable",
);
check(
  pathContractScript.includes("export async function readRegularFileWithoutLinks") &&
    pathContractScript.includes("export async function sha256RegularFileWithoutLinks") &&
    pathContractScript.includes("export async function copyRegularFileExclusiveWithoutLinks") &&
    prepareRuntimeScript.includes('".requirements-inputs"') &&
    prepareRuntimeScript.includes("runPinnedCommand(") &&
    prepareRuntimeScript.includes("files: [pythonPin, sourcePin") &&
    prepareRuntimeScript.includes("expectedDestinationParentIdentity: requirementsInputRootIdentity"),
  "runtime subprocesses must consume identity-bound Python, archive, and requirements snapshots",
);
check(
  prepareRuntimeScript.includes("replaceDirectoryTransactionally(stagingRuntime, outputRuntime") &&
    prepareRuntimeScript.includes("replaceDirectoryTransactionally(stagingWheels, wheelsDir") &&
    prepareRuntimeScript.includes("portableTemporaryPathPrefix(`${outputRuntime}.tmp-`") &&
    prepareRuntimeScript.includes("portableTemporaryPathPrefix(`${wheelsDir}.tmp-`") &&
    !prepareRuntimeScript.includes("await rm(outputRuntime, { force: true, recursive: true })") &&
    !prepareRuntimeScript.includes("await rm(wheelsDir, { force: true, recursive: true })"),
  "runtime and wheel publication must use private siblings and preserve the previous complete directory until replacement succeeds",
);
check(
  prepareRuntimeScript.includes('await mkdtemp(path.join(outputDirectory, ".runtime-download-"))') &&
    prepareRuntimeScript.includes('createWriteStream(outputPath, { flags: "wx" })') &&
    prepareRuntimeScript.includes("await link(privatePath, tempPath)") &&
    prepareRuntimeScript.includes("replaceFileTransactionally(tempPath, outputPath"),
  "runtime downloads must use a private directory, exclusive writes, no-overwrite staging, and transactional cache publication",
);
check(
  prepareTauriResourcesScript.includes("portableTemporaryPathPrefix(`${stageRoot}.tmp-`") &&
    prepareTauriResourcesScript.includes("expectedIdentity: stagingRootIdentity") &&
    prepareTauriResourcesScript.includes("removeDirectoryWithoutLinks(stagingRoot") &&
    prepareTauriResourcesScript.includes("replaceDirectoryTransactionally(stagingRoot, stageRoot") &&
    !prepareTauriResourcesScript.includes("await rm("),
  "Tauri resources must be assembled in a private sibling and published transactionally",
);
check(
  prepareRuntimeScript.includes("expectedIdentity: extractRootIdentity") &&
    prepareRuntimeScript.includes("expectedIdentity: stagingRuntimeIdentity") &&
    prepareRuntimeScript.includes("expectedIdentity: stagingWheelsIdentity") &&
    prepareRuntimeScript.includes("expectedIdentity: privateDownloadRootIdentity") &&
    prepareRuntimeScript.includes("expectedIdentity: tempPathIdentity"),
  "runtime temporary cleanup must preserve the identity captured when each private path was created",
);
check(
  tauriResourcePlanScript.includes("export async function collectTauriResourceMappings") &&
    tauriResourcePlanScript.includes("assertContainedDirectoryTree(sourceRoot") &&
    tauriResourcePlanScript.includes("assertRegularFileWithoutLinks(") &&
    prepareTauriResourcesScript.includes('from "./tauri-resource-plan.mjs"') &&
    verifyTauriResourcesScript.includes('from "./tauri-resource-plan.mjs"'),
  "Tauri preparation and verification must share one link-free source-to-destination resource plan",
);
check(
  verifyTauriResourcesScript.includes("assertRegularFileWithoutLinks(filePath") &&
    verifyTauriResourcesScript.includes(
      'resolveExactRelativePath(runtimeRoot, requiredFile, "embedded runtime required file")',
    ) &&
    verifyPackagedRuntimeScript.includes("assertRegularFileWithoutLinks(filePath") &&
    verifyPackagedRuntimeScript.includes(
      'resolveExactRelativePath(runtimeRoot, requiredFile, "packaged runtime required file")',
    ),
  "resource verification must require exact runtime-relative regular non-link files",
);

async function readStrictText(filePath, field) {
  return (
    await readRegularFileWithoutLinks(filePath, {
      field,
      encoding: "utf8",
    })
  ).data;
}
check(
  prepareRuntimeScript.includes('resolveAbsoluteEnvironmentPath("SHINSEKAI_PBS_CACHE_DIR"') &&
    prepareRuntimeScript.includes('resolveAbsoluteEnvironmentPath("SHINSEKAI_RUNTIME_OUTPUT_DIR"') &&
    prepareRuntimeScript.includes('resolveAbsoluteEnvironmentPath("SHINSEKAI_RUNTIME_WHEEL_DIR"') &&
    prepareTauriResourcesScript.includes('resolveAbsoluteEnvironmentPath("SHINSEKAI_TAURI_RUNTIME_DIR"') &&
    /resolveAbsoluteEnvironmentPath\(\s*"SHINSEKAI_TAURI_TARGET_DIR"/u.test(verifyPackagedRuntimeScript),
  "all build-time filesystem environment paths must use the shared exact absolute resolver",
);
check(
  packageJson.scripts?.["test:path-contract"] === "node --test scripts/path-contract.test.mjs" &&
    packageJson.scripts?.test?.startsWith("pnpm test:path-contract &&") &&
    packageJson.scripts?.["test:coverage"]?.startsWith("pnpm test:path-contract &&"),
  "frontend test entrypoints must enforce the build path contract",
);
check(
  prepareRuntimeScript.includes('"--skip-wheels"'),
  "prepare-runtime must expose a --skip-wheels mode for installer builds",
);
check(
  !prepareTauriResourcesScript.includes("SHINSEKAI_TAURI_WHEELS_DIR") &&
    !prepareTauriResourcesScript.includes('path.join(stageRoot, "wheels")') &&
    prepareTauriResourcesScript.includes("Runtime dependency repair will use configured pip indexes."),
  "prepare-tauri-resources must not stage runtime wheels into the installer",
);
check(
  !verifyTauriResourcesScript.includes(".shinsekai-wheels.json") &&
    !verifyPackagedRuntimeScript.includes(".shinsekai-wheels.json") &&
    verifyTauriResourcesScript.includes("requirements-runtime-core.txt") &&
    verifyPackagedRuntimeScript.includes("requirements-runtime-core.txt"),
  "resource verification must require runtime requirements but no wheelhouse marker",
);

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`- ${error}`);
  }
  process.exit(1);
}

console.log(`Verified embedded Python runtime matrix for ${expectedTargets.length} targets`);

function check(condition, message) {
  if (!condition) {
    errors.push(message);
  }
}

function sameList(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function workflowBuildMatrix() {
  return new Map(
    [...workflow.matchAll(/^\s+- platform:\s*([^\s#]+)\s*\n\s+os:\s*([^\n#]+)\s*\n\s+bundles:\s*([^\s#]+)/gm)].map(
      (match) => [
        match[1],
        {
          os: match[2].trim(),
          bundles: match[3].trim(),
        },
      ],
    ),
  );
}

function splitBundles(value) {
  return String(value)
    .split(",")
    .map((bundle) => bundle.trim())
    .filter(Boolean);
}
