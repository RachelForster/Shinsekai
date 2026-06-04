import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(frontendDir, "..");

const runtimeSourcesPath = path.join(frontendDir, "src-tauri", "runtime_sources.json");
const workflowPath = path.join(repoRoot, ".github", "workflows", "tauri-desktop.yml");
const packageJsonPath = path.join(frontendDir, "package.json");
const tauriConfigPath = path.join(frontendDir, "src-tauri", "tauri.conf.json");
const prepareRuntimeScriptPath = path.join(frontendDir, "scripts", "prepare-runtime.mjs");

const expectedTargets = ["linux-x64", "linux-arm64", "windows-x64", "macos-arm64"];
const linuxTriples = new Map([
  ["linux-x64", "x86_64-unknown-linux-gnu"],
  ["linux-arm64", "aarch64-unknown-linux-gnu"],
]);
const linuxRuntimePruneFiles = ["lib/python*/lib-dynload/_tkinter.*.so"];
const windowsRequiredFiles = new Map([
  ["windows-x64", ["python.exe", "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll"]],
]);
const expectedBundles = new Map([
  ["linux-x64", ["deb", "rpm", "appimage"]],
  ["linux-arm64", ["deb", "rpm", "appimage"]],
  ["windows-x64", ["msi", "nsis"]],
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

const runtimeSources = JSON.parse(await readFile(runtimeSourcesPath, "utf8"));
const workflow = await readFile(workflowPath, "utf8");
const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
const tauriConfig = JSON.parse(await readFile(tauriConfigPath, "utf8"));
const prepareRuntimeScript = await readFile(prepareRuntimeScriptPath, "utf8");

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
      `${targetName} must prune unused Tk runtime extension for AppImage packaging`,
    );
  }

  if (targetName.startsWith("macos-")) {
    check(target.python.startsWith("3.10."), `${targetName} should stay on Python 3.10`);
    check(
      target.required_files.includes("bin/python3.10"),
      `${targetName} must include the PBS Python 3.10 executable`,
    );
  }

  if (targetName === "windows-x64") {
    check(target.python.startsWith("3.10."), "windows-x64 should stay on Python 3.10");
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
  "pnpm prepare:runtime --verify",
  "pnpm prepare:tauri-resources",
  "pnpm verify:tauri-resources",
]) {
  check(beforeBuildCommand.includes(command), `Tauri beforeBuildCommand must include ${command}`);
}
check(tauriConfig.bundle?.resources?.["resources/"] === "", "Tauri bundle must include the staged resources directory");
check(
  workflow.includes("pnpm prepare:runtime --target ${{ matrix.platform }} --verify"),
  "workflow build job must prepare and verify the target-specific embedded runtime before packaging",
);
check(
  workflow.includes("actions/cache/restore@v4") &&
    workflow.includes("actions/cache/save@v4") &&
    workflow.includes("embedded-python-runtime-${{ runner.os }}-${{ matrix.platform }}"),
  "workflow build job must cache embedded Python runtime and wheelhouse per target",
);
check(
  workflow.includes("pnpm verify:packaged-runtime --target ${{ matrix.platform }} --require-installers"),
  "workflow build job must verify the packaged embedded runtime and installer artifacts after packaging",
);
check(
  !prepareRuntimeScript.includes('["-xzf", archivePath, "-C", extractRoot]'),
  "prepare-runtime must not pass an absolute archivePath directly to tar on Windows",
);
check(
  prepareRuntimeScript.includes("toPosixRelativePath(extractRoot, archivePath)") &&
    prepareRuntimeScript.includes("cwd: extractRoot"),
  "prepare-runtime must extract tar archives from extractRoot with a relative archive path",
);
check(
  prepareRuntimeScript.includes("buildSourceArchivesIntoWheels(stagingWheels, python)"),
  "prepare-runtime must build downloaded source archives into wheels before packaging",
);
check(
  prepareRuntimeScript.includes("assertNoSourceArchives(stagingWheels)") &&
    prepareRuntimeScript.includes("assertNoSourceArchives(wheelsDir)"),
  "prepare-runtime must reject source archives in the packaged runtime wheelhouse",
);
check(
  prepareRuntimeScript.includes('"pip", "wheel"') && prepareRuntimeScript.includes('"--no-deps"'),
  "prepare-runtime must convert source archives with pip wheel --no-deps",
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
