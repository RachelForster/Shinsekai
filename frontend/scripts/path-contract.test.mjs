import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { rename } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
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
  fitPortablePathComponentWithSuffix,
  portableTemporaryPathPrefix,
  portableSiblingPath,
  portableWindowsExecutableCandidateNames,
  removeDirectoryWithoutLinks,
  removeFileWithoutLinks,
  readRegularFileWithoutLinks,
  replaceDirectoryTransactionally,
  replaceFileTransactionally,
  portableWindowsExecutableExtensions,
  requireDirectorySnapshot,
  requireExecutableSnapshot,
  requireRegularFileSnapshot,
  resolveAbsoluteEnvironmentPath,
  resolveExactAbsolutePath,
  resolveExactRelativePath,
  sha256RegularFileWithoutLinks,
  validateArchiveLinkTarget,
  validateArchiveMemberSet,
  validateExactArchiveMemberPath,
} from "./path-contract.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const repositoryDirectory = path.resolve(frontendDirectory, "..");

test("an absent environment path uses the explicit fallback without consulting cwd", () => {
  const name = "SHINSEKAI_TEST_ABSENT_PATH";
  delete process.env[name];
  const fallback = path.join(os.tmpdir(), "新世界 fallback");

  assert.equal(resolveAbsoluteEnvironmentPath(name, fallback), path.resolve(fallback));
});

test("shared path roots reject relative values instead of consulting cwd", () => {
  const name = "SHINSEKAI_TEST_RELATIVE_FALLBACK";
  delete process.env[name];

  assert.throws(() => resolveAbsoluteEnvironmentPath(name, "relative/cache"), /absolute path/u);
  assert.throws(() => resolveExactRelativePath("relative/root", "requirements/runtime.txt"), /absolute path/u);
  assert.throws(() => assertSafeMutableDirectory("relative/output", { field: "runtime output" }), /absolute path/u);
});

test("a present environment path is authoritative and must be exact and absolute", () => {
  const name = "SHINSEKAI_TEST_EXPLICIT_PATH";
  const valid = path.join(os.tmpdir(), "新世界 runtime");
  const invalidValues = [
    "",
    "relative/runtime",
    ` ${valid}`,
    `${valid} `,
    `${path.dirname(valid)}${path.sep}.${path.sep}${path.basename(valid)}`,
    `${valid}${path.sep}`,
  ];

  try {
    for (const value of invalidValues) {
      process.env[name] = value;
      assert.throws(() => resolveAbsoluteEnvironmentPath(name, valid));
    }

    process.env[name] = valid;
    assert.equal(resolveAbsoluteEnvironmentPath(name, path.parse(valid).root), path.resolve(valid));
  } finally {
    delete process.env[name];
  }
});

test("exact paths reject lone Unicode surrogates before filesystem encoding changes identity", () => {
  const invalidAbsolute = `${os.tmpdir()}${path.sep}invalid-\ud800`;

  assert.throws(() => resolveExactAbsolutePath(invalidAbsolute), /control characters/u);
  assert.throws(() => resolveExactRelativePath(os.tmpdir(), "data/invalid-\udfff"), /control characters/u);
});

test("portable components enforce the common 255-byte filesystem boundary", () => {
  assert.doesNotThrow(() => resolveExactRelativePath(os.tmpdir(), `data/${"界".repeat(85)}`));
  assert.throws(() => resolveExactRelativePath(os.tmpdir(), `data/${"界".repeat(86)}`), /non-portable path component/u);
  assert.throws(() => resolveExactRelativePath(os.tmpdir(), `data/${"a".repeat(256)}`), /non-portable path component/u);
});

test("derived sibling names preserve suffixes within the portable byte boundary", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-long-sibling-"));
  const component = `${"界".repeat(83)}ab.txt`;
  const target = path.join(temporaryRoot, component);
  const suffix = `.backup-${"x".repeat(36)}`;
  const fitted = fitPortablePathComponentWithSuffix(component, suffix);
  const sibling = portableSiblingPath(target, suffix);
  const temporaryPrefix = portableTemporaryPathPrefix(`${target}.tmp-`);

  assert.ok(Buffer.byteLength(fitted, "utf8") <= 255);
  assert.equal(path.basename(sibling), fitted);
  assert.ok(fitted.endsWith(suffix));
  assert.ok(Buffer.byteLength(path.basename(temporaryPrefix), "utf8") + 16 <= 255);

  try {
    writeFileSync(target, "old");
    await removeFileWithoutLinks(target, {
      expectedIdentity: lstatSync(target, { bigint: true }),
      field: "maximum-length file",
    });
    assert.equal(existsSync(target), false);

    const staging = path.join(temporaryRoot, "staging.txt");
    writeFileSync(target, "old");
    writeFileSync(staging, "new");
    await replaceFileTransactionally(staging, target, {
      field: "maximum-length publication",
    });
    assert.equal(readFileSync(target, "utf8"), "new");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("mutable build directories cannot target roots, source trees, or overlapping storage", () => {
  const repository = path.join(os.tmpdir(), "shinsekai-path-contract-repository");
  const runtime = path.join(repository, "runtime");
  const wheels = path.join(repository, "wheels");

  assert.throws(() =>
    assertSafeMutableDirectory(path.parse(repository).root, {
      field: "runtime output",
      protectedRoots: [repository],
      allowedRoots: [runtime],
    }),
  );
  assert.throws(() =>
    assertSafeMutableDirectory(repository, {
      field: "runtime output",
      protectedRoots: [repository],
      allowedRoots: [runtime],
    }),
  );
  assert.throws(() =>
    assertSafeMutableDirectory(path.join(repository, "core"), {
      field: "runtime output",
      protectedRoots: [repository],
      allowedRoots: [runtime],
    }),
  );
  assert.equal(
    assertSafeMutableDirectory(runtime, {
      field: "runtime output",
      protectedRoots: [repository],
      allowedRoots: [runtime],
    }),
    runtime,
  );
  assert.doesNotThrow(() =>
    assertNonOverlappingDirectories([
      { field: "runtime output", path: runtime },
      { field: "wheel output", path: wheels },
    ]),
  );
  assert.throws(() =>
    assertNonOverlappingDirectories([
      { field: "runtime output", path: runtime },
      { field: "wheel output", path: path.join(runtime, "wheels") },
    ]),
  );
  assert.throws(() =>
    assertNonOverlappingDirectories([
      { field: "runtime output", path: path.join(repository, "Runtime") },
      { field: "wheel output", path: path.join(repository, "runtime", "wheels") },
    ]),
  );
  assert.throws(() =>
    assertNonOverlappingDirectories([
      { field: "runtime output", path: path.join(repository, "caf\u00e9") },
      { field: "wheel output", path: path.join(repository, "cafe\u0301", "wheels") },
    ]),
  );
});

test("mutable build directories reject existing symbolic-link components", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-path-contract-"));
  const real = path.join(temporaryRoot, "real");
  const alias = path.join(temporaryRoot, "alias");
  mkdirSync(real);
  try {
    symlinkSync(real, alias, "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("directory symbolic links are unavailable");
    return;
  }

  try {
    assert.throws(
      () =>
        assertSafeMutableDirectory(path.join(alias, "runtime"), {
          field: "runtime output",
        }),
      /symbolic-link/u,
    );
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("mutable build directories reject dangling symbolic-link components", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-path-contract-dangling-"));
  const alias = path.join(temporaryRoot, "missing-alias");
  try {
    symlinkSync(path.join(temporaryRoot, "does-not-exist"), alias, "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("directory symbolic links are unavailable");
    return;
  }

  try {
    assert.throws(
      () =>
        assertSafeMutableDirectory(path.join(alias, "runtime"), {
          field: "runtime output",
        }),
      /symbolic-link/u,
    );
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("mutable build directories reject an existing regular file", () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-path-contract-file-"));
  const candidate = path.join(temporaryRoot, "runtime");
  writeFileSync(candidate, "not a directory");
  try {
    assert.throws(
      () => assertSafeMutableDirectory(candidate, { field: "runtime output" }),
      /regular non-link directory/u,
    );
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("regular file checks reject linked leaves and linked parents", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-file-contract-"));
  const realDirectory = path.join(temporaryRoot, "real");
  const realFile = path.join(realDirectory, "archive.tar.gz");
  const fileAlias = path.join(temporaryRoot, "archive-alias.tar.gz");
  const directoryAlias = path.join(temporaryRoot, "directory-alias");
  mkdirSync(realDirectory);
  writeFileSync(realFile, "archive");
  try {
    symlinkSync(realFile, fileAlias, "file");
    symlinkSync(realDirectory, directoryAlias, "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("symbolic links are unavailable");
    return;
  }

  try {
    assert.equal(assertRegularFileWithoutLinks(realFile, "runtime archive"), realFile);
    assert.throws(() => assertRegularFileWithoutLinks(fileAlias, "runtime archive"), /symbolic-link/u);
    assert.throws(
      () => assertRegularFileWithoutLinks(path.join(directoryAlias, "archive.tar.gz"), "runtime archive"),
      /symbolic-link/u,
    );
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("executable snapshots ignore cwd-dependent PATH entries and detect replacement", async (context) => {
  if (process.platform === "win32") {
    context.skip("the executable permission and symbolic-link assertions are POSIX-specific");
    return;
  }
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-executable-contract-"));
  const binDirectory = path.join(temporaryRoot, "bin");
  const target = path.join(binDirectory, "tool-target");
  const alias = path.join(binDirectory, "tool");
  const preserved = path.join(binDirectory, "tool-preserved");
  mkdirSync(binDirectory);
  writeFileSync(target, "#!/bin/sh\nexit 0\n");
  chmodSync(target, 0o755);
  try {
    symlinkSync(target, alias, "file");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("file symbolic links are unavailable");
    return;
  }

  try {
    const snapshot = captureExecutableSnapshot("tool", {
      field: "test tool",
      searchPath: `.${path.delimiter}${binDirectory}`,
    });
    assert.equal(snapshot.path, target);
    assert.equal(requireExecutableSnapshot(snapshot, "test tool"), target);

    assert.throws(
      () =>
        captureExecutableSnapshot("tool", {
          field: "test tool",
          searchPath: ".",
        }),
      /deterministic PATH/u,
    );

    await rename(target, preserved);
    writeFileSync(target, "#!/bin/sh\nexit 0\n");
    chmodSync(target, 0o755);
    assert.throws(() => requireExecutableSnapshot(snapshot, "test tool"), /identity changed/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("Windows executable extensions reject aliases and non-portable suffixes", () => {
  assert.deepEqual(portableWindowsExecutableExtensions(".COM;.EXE;..EXE;.EXE.;.工具; .CMD;.BAT "), [".COM", ".EXE"]);
  assert.deepEqual(portableWindowsExecutableCandidateNames("a".repeat(251), ".EXE;.工具"), [`${"a".repeat(251)}.EXE`]);
  assert.deepEqual(portableWindowsExecutableCandidateNames("a".repeat(252), ".EXE"), []);
});

test("environment path aliases are canonicalized once and remain identity-bound", async (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-environment-path-contract-"));
  const realDirectory = path.join(temporaryRoot, "certificates");
  const directoryAlias = path.join(temporaryRoot, "certificates-alias");
  const certificate = path.join(realDirectory, "ca.pem");
  const certificateAlias = path.join(temporaryRoot, "ca-alias.pem");
  const preserved = path.join(realDirectory, "ca-preserved.pem");
  mkdirSync(realDirectory);
  writeFileSync(certificate, "certificate");
  try {
    symlinkSync(realDirectory, directoryAlias, "dir");
    symlinkSync(certificate, certificateAlias, "file");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("symbolic links are unavailable");
    return;
  }

  try {
    const fileSnapshot = captureRegularFileAliasSnapshot(certificateAlias, "certificate bundle");
    const directorySnapshot = captureDirectoryAliasSnapshot(directoryAlias, "certificate directory");
    assert.equal(fileSnapshot.path, certificate);
    assert.equal(directorySnapshot.path, realDirectory);
    assert.equal(requireRegularFileSnapshot(fileSnapshot, "certificate bundle"), certificate);
    assert.equal(requireDirectorySnapshot(directorySnapshot, "certificate directory"), realDirectory);

    await rename(certificate, preserved);
    writeFileSync(certificate, "replacement");
    assert.throws(() => requireRegularFileSnapshot(fileSnapshot, "certificate bundle"), /identity changed/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("identity-bound reads and hashes reject replaced files and parents", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-bound-read-"));
  const parent = path.join(temporaryRoot, "inputs");
  const preservedParent = path.join(temporaryRoot, "inputs-preserved");
  const file = path.join(parent, "requirements.txt");
  const preservedFile = path.join(parent, "requirements-preserved.txt");
  mkdirSync(parent);
  writeFileSync(file, "original\n");
  const fileIdentity = lstatSync(file, { bigint: true });
  const parentIdentity = lstatSync(parent, { bigint: true });

  try {
    const read = await readRegularFileWithoutLinks(file, {
      field: "runtime requirements",
      encoding: "utf8",
      expectedIdentity: fileIdentity,
      expectedParentIdentity: parentIdentity,
    });
    assert.equal(read.data, "original\n");
    assert.equal(
      (
        await sha256RegularFileWithoutLinks(file, {
          field: "runtime requirements",
          expectedIdentity: fileIdentity,
          expectedParentIdentity: parentIdentity,
        })
      ).sha256,
      "25718360e05d3c2d0963d1381e9dd4dae5fca789244ee4b9f861adcc0cc96218",
    );

    await rename(file, preservedFile);
    writeFileSync(file, "peer\n");
    await assert.rejects(
      readRegularFileWithoutLinks(file, {
        field: "runtime requirements",
        expectedIdentity: fileIdentity,
        expectedParentIdentity: parentIdentity,
      }),
      /identity changed/u,
    );
    assert.equal(readFileSync(file, "utf8"), "peer\n");
    assert.equal(readFileSync(preservedFile, "utf8"), "original\n");

    rmSync(file);
    await rename(parent, preservedParent);
    mkdirSync(parent);
    writeFileSync(file, "new parent\n");
    await assert.rejects(
      sha256RegularFileWithoutLinks(file, {
        field: "runtime requirements",
        expectedParentIdentity: parentIdentity,
      }),
      /parent identity changed/u,
    );
    assert.equal(readFileSync(file, "utf8"), "new parent\n");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("identity-bound exclusive copies preserve peers and reject stale sources", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-bound-copy-"));
  const source = path.join(temporaryRoot, "runtime.tar.gz");
  const preservedSource = path.join(temporaryRoot, "runtime-preserved.tar.gz");
  const destination = path.join(temporaryRoot, "private.tar.gz");
  writeFileSync(source, "archive");
  const sourceIdentity = lstatSync(source, { bigint: true });
  const parentIdentity = lstatSync(temporaryRoot, { bigint: true });

  try {
    const copied = await copyRegularFileExclusiveWithoutLinks(source, destination, {
      field: "runtime archive snapshot",
      expectedSourceIdentity: sourceIdentity,
      expectedSourceParentIdentity: parentIdentity,
      expectedDestinationParentIdentity: parentIdentity,
      expectedSha256: "0eb3e36bfb24dcd9bb1d1bece1531216b59539a8fde17ee80224af0653c92aa3",
    });
    assert.equal(readFileSync(destination, "utf8"), "archive");
    assert.equal(copied.sha256, "0eb3e36bfb24dcd9bb1d1bece1531216b59539a8fde17ee80224af0653c92aa3");

    await assert.rejects(
      copyRegularFileExclusiveWithoutLinks(source, destination, {
        field: "runtime archive snapshot",
      }),
      /destination already exists/u,
    );
    assert.equal(readFileSync(destination, "utf8"), "archive");

    await rename(source, preservedSource);
    writeFileSync(source, "peer");
    const secondDestination = path.join(temporaryRoot, "second.tar.gz");
    await assert.rejects(
      copyRegularFileExclusiveWithoutLinks(source, secondDestination, {
        field: "runtime archive snapshot",
        expectedSourceIdentity: sourceIdentity,
        expectedSourceParentIdentity: parentIdentity,
        expectedDestinationParentIdentity: parentIdentity,
      }),
      /identity changed/u,
    );
    assert.equal(existsSync(secondDestination), false);
    assert.equal(readFileSync(source, "utf8"), "peer");
    assert.equal(readFileSync(preservedSource, "utf8"), "archive");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("identity-preserving removal deletes exact files and directories", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-removal-contract-"));
  const file = path.join(temporaryRoot, "managed.json");
  const directory = path.join(temporaryRoot, "managed");
  writeFileSync(file, "content");
  mkdirSync(directory);

  try {
    await removeFileWithoutLinks(file, {
      expectedIdentity: lstatSync(file, { bigint: true }),
      field: "managed file",
    });
    await removeDirectoryWithoutLinks(directory, {
      expectedIdentity: lstatSync(directory, { bigint: true }),
      field: "managed directory",
    });

    assert.equal(readdirSync(temporaryRoot).length, 0);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("identity-preserving removal preserves a replacement identity", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-removal-replacement-"));
  const file = path.join(temporaryRoot, "managed.json");
  const preserved = path.join(temporaryRoot, "preserved.json");
  writeFileSync(file, "original");
  const expectedIdentity = lstatSync(file, { bigint: true });
  await rename(file, preserved);
  writeFileSync(file, "replacement");

  try {
    await assert.rejects(
      removeFileWithoutLinks(file, {
        expectedIdentity,
        field: "managed file",
      }),
      /identity changed/u,
    );
    assert.equal(readFileSync(file, "utf8"), "replacement");
    assert.equal(readFileSync(preserved, "utf8"), "original");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("identity-preserving directory removal preserves a replacement identity", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-directory-removal-replacement-"));
  const directory = path.join(temporaryRoot, "managed");
  const preserved = path.join(temporaryRoot, "preserved");
  mkdirSync(directory);
  writeFileSync(path.join(directory, "original.txt"), "original");
  const expectedIdentity = lstatSync(directory, { bigint: true });
  await rename(directory, preserved);
  mkdirSync(directory);
  writeFileSync(path.join(directory, "replacement.txt"), "replacement");

  try {
    await assert.rejects(
      removeDirectoryWithoutLinks(directory, {
        expectedIdentity,
        field: "managed directory",
      }),
      /identity changed/u,
    );
    assert.equal(readFileSync(path.join(directory, "replacement.txt"), "utf8"), "replacement");
    assert.equal(readFileSync(path.join(preserved, "original.txt"), "utf8"), "original");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("directory publication replaces a complete tree and removes its private backup", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-directory-publication-"));
  const destination = path.join(temporaryRoot, "runtime");
  const staging = path.join(temporaryRoot, "runtime.tmp");
  mkdirSync(destination);
  mkdirSync(staging);
  writeFileSync(path.join(destination, "old.txt"), "old");
  writeFileSync(path.join(staging, "new.txt"), "new");

  try {
    await replaceDirectoryTransactionally(staging, destination, {
      field: "embedded runtime",
    });

    assert.equal(readFileSync(path.join(destination, "new.txt"), "utf8"), "new");
    assert.equal(readdirSync(temporaryRoot).filter((name) => name.includes(".backup-")).length, 0);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("file publication replaces a complete file and removes its private backup", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-file-publication-"));
  const destination = path.join(temporaryRoot, "runtime.tar.gz");
  const staging = path.join(temporaryRoot, "runtime.tar.gz.download");
  writeFileSync(destination, "old");
  writeFileSync(staging, "new");

  try {
    await replaceFileTransactionally(staging, destination, {
      field: "runtime archive",
    });

    assert.equal(readFileSync(destination, "utf8"), "new");
    assert.equal(existsSync(staging), false);
    assert.equal(readdirSync(temporaryRoot).filter((name) => name.includes(".backup-")).length, 0);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("file publication rejects stale caller-owned staging and destination identities", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-file-publication-identity-"));
  const destination = path.join(temporaryRoot, "runtime.tar.gz");
  const staging = path.join(temporaryRoot, "runtime.tar.gz.download");
  const preservedStaging = path.join(temporaryRoot, "preserved-staging.tar.gz");
  const preservedDestination = path.join(temporaryRoot, "preserved-destination.tar.gz");
  writeFileSync(destination, "old");
  writeFileSync(staging, "new");
  const stagingIdentity = lstatSync(staging, { bigint: true });
  const destinationIdentity = lstatSync(destination, { bigint: true });

  try {
    await rename(staging, preservedStaging);
    writeFileSync(staging, "peer staging");
    await assert.rejects(
      replaceFileTransactionally(staging, destination, {
        expectedStagingIdentity: stagingIdentity,
        field: "runtime archive",
      }),
      /staging file identity changed/u,
    );
    assert.equal(readFileSync(staging, "utf8"), "peer staging");
    assert.equal(readFileSync(destination, "utf8"), "old");

    rmSync(staging);
    writeFileSync(staging, "new");
    await rename(destination, preservedDestination);
    writeFileSync(destination, "peer destination");
    await assert.rejects(
      replaceFileTransactionally(staging, destination, {
        expectedDestinationIdentity: destinationIdentity,
        field: "runtime archive",
      }),
      /destination file identity changed/u,
    );
    assert.equal(readFileSync(staging, "utf8"), "new");
    assert.equal(readFileSync(destination, "utf8"), "peer destination");
    assert.equal(readFileSync(preservedDestination, "utf8"), "old");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("directory publication rejects stale caller-owned staging and destination identities", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-directory-publication-identity-"));
  const destination = path.join(temporaryRoot, "runtime");
  const staging = path.join(temporaryRoot, "runtime.tmp");
  const preservedStaging = path.join(temporaryRoot, "preserved-staging");
  const preservedDestination = path.join(temporaryRoot, "preserved-destination");
  mkdirSync(destination);
  mkdirSync(staging);
  writeFileSync(path.join(destination, "old.txt"), "old");
  writeFileSync(path.join(staging, "new.txt"), "new");
  const stagingIdentity = lstatSync(staging, { bigint: true });
  const destinationIdentity = lstatSync(destination, { bigint: true });

  try {
    await rename(staging, preservedStaging);
    mkdirSync(staging);
    writeFileSync(path.join(staging, "peer.txt"), "peer staging");
    await assert.rejects(
      replaceDirectoryTransactionally(staging, destination, {
        expectedStagingIdentity: stagingIdentity,
        field: "embedded runtime",
      }),
      /staging directory identity changed/u,
    );
    assert.equal(readFileSync(path.join(staging, "peer.txt"), "utf8"), "peer staging");
    assert.equal(readFileSync(path.join(destination, "old.txt"), "utf8"), "old");

    rmSync(staging, { recursive: true });
    mkdirSync(staging);
    writeFileSync(path.join(staging, "new.txt"), "new");
    await rename(destination, preservedDestination);
    mkdirSync(destination);
    writeFileSync(path.join(destination, "peer.txt"), "peer destination");
    await assert.rejects(
      replaceDirectoryTransactionally(staging, destination, {
        expectedDestinationIdentity: destinationIdentity,
        field: "embedded runtime",
      }),
      /destination directory identity changed/u,
    );
    assert.equal(readFileSync(path.join(staging, "new.txt"), "utf8"), "new");
    assert.equal(readFileSync(path.join(destination, "peer.txt"), "utf8"), "peer destination");
    assert.equal(readFileSync(path.join(preservedDestination, "old.txt"), "utf8"), "old");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("file and directory publication reject a replaced caller-owned parent", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-publication-parent-identity-"));
  const parent = path.join(temporaryRoot, "outputs");
  const preservedParent = path.join(temporaryRoot, "outputs-preserved");
  mkdirSync(parent);
  const parentIdentity = lstatSync(parent, { bigint: true });

  try {
    await rename(parent, preservedParent);
    mkdirSync(parent);

    const fileStaging = path.join(parent, "runtime.tar.gz.download");
    const fileDestination = path.join(parent, "runtime.tar.gz");
    writeFileSync(fileStaging, "stale");
    writeFileSync(fileDestination, "peer");
    await assert.rejects(
      replaceFileTransactionally(fileStaging, fileDestination, {
        expectedParentIdentity: parentIdentity,
        field: "runtime archive",
      }),
      /parent identity changed/u,
    );
    assert.equal(readFileSync(fileStaging, "utf8"), "stale");
    assert.equal(readFileSync(fileDestination, "utf8"), "peer");

    const directoryStaging = path.join(parent, "runtime.tmp");
    const directoryDestination = path.join(parent, "runtime");
    mkdirSync(directoryStaging);
    mkdirSync(directoryDestination);
    writeFileSync(path.join(directoryStaging, "new.txt"), "stale");
    writeFileSync(path.join(directoryDestination, "old.txt"), "peer");
    await assert.rejects(
      replaceDirectoryTransactionally(directoryStaging, directoryDestination, {
        expectedParentIdentity: parentIdentity,
        field: "embedded runtime",
      }),
      /parent identity changed/u,
    );
    assert.equal(readFileSync(path.join(directoryStaging, "new.txt"), "utf8"), "stale");
    assert.equal(readFileSync(path.join(directoryDestination, "old.txt"), "utf8"), "peer");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("file publication rejects a linked destination without touching its target", async (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-file-publication-link-"));
  const external = path.join(temporaryRoot, "external.tar.gz");
  const destination = path.join(temporaryRoot, "runtime.tar.gz");
  const staging = path.join(temporaryRoot, "runtime.tar.gz.download");
  writeFileSync(external, "external");
  writeFileSync(staging, "new");
  try {
    symlinkSync(external, destination, "file");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("file symbolic links are unavailable");
    return;
  }

  try {
    await assert.rejects(
      replaceFileTransactionally(staging, destination, {
        field: "runtime archive",
      }),
      /symbolic-link/u,
    );
    assert.equal(readFileSync(external, "utf8"), "external");
    assert.equal(readFileSync(staging, "utf8"), "new");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("directory publication rejects a linked destination without touching either tree", async (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-directory-publication-link-"));
  const external = path.join(temporaryRoot, "external");
  const destination = path.join(temporaryRoot, "runtime");
  const staging = path.join(temporaryRoot, "runtime.tmp");
  mkdirSync(external);
  mkdirSync(staging);
  writeFileSync(path.join(external, "keep.txt"), "keep");
  writeFileSync(path.join(staging, "new.txt"), "new");
  try {
    symlinkSync(external, destination, "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("directory symbolic links are unavailable");
    return;
  }

  try {
    await assert.rejects(
      replaceDirectoryTransactionally(staging, destination, {
        field: "embedded runtime",
      }),
      /symbolic-link/u,
    );
    assert.equal(readFileSync(path.join(external, "keep.txt"), "utf8"), "keep");
    assert.equal(readFileSync(path.join(staging, "new.txt"), "utf8"), "new");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("directory publication rejects links introduced inside the staging tree", async (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-directory-publication-staging-link-"));
  const external = path.join(temporaryRoot, "external");
  const destination = path.join(temporaryRoot, "runtime");
  const staging = path.join(temporaryRoot, "runtime.tmp");
  mkdirSync(external);
  mkdirSync(staging);
  writeFileSync(path.join(external, "private.txt"), "private");
  try {
    symlinkSync(external, path.join(staging, "linked"), "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("directory symbolic links are unavailable");
    return;
  }

  try {
    await assert.rejects(
      replaceDirectoryTransactionally(staging, destination, {
        field: "embedded runtime",
      }),
      /symbolic link/u,
    );
    assert.equal(readFileSync(path.join(external, "private.txt"), "utf8"), "private");
    assert.equal(readdirSync(temporaryRoot).filter((name) => name.includes(".backup-")).length, 0);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("directory publication rejects portable sibling-name collisions", async () => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-directory-publication-collision-"));
  const destination = path.join(temporaryRoot, "runtime");
  const staging = path.join(temporaryRoot, "runtime.tmp");
  mkdirSync(path.join(temporaryRoot, "Runtime"));
  mkdirSync(staging);
  writeFileSync(path.join(staging, "new.txt"), "new");

  try {
    await assert.rejects(
      replaceDirectoryTransactionally(staging, destination, {
        field: "embedded runtime",
      }),
      /portable filename collision/u,
    );
    assert.equal(readFileSync(path.join(staging, "new.txt"), "utf8"), "new");
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("copied directory trees allow only contained symbolic links", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-copy-contract-"));
  const tree = path.join(temporaryRoot, "tree");
  const internal = path.join(tree, "internal");
  const external = path.join(temporaryRoot, "external");
  mkdirSync(internal, { recursive: true });
  mkdirSync(external);
  try {
    symlinkSync(internal, path.join(tree, "internal-link"), "dir");
    symlinkSync(external, path.join(tree, "external-link"), "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("directory symbolic links are unavailable");
    return;
  }

  try {
    assert.throws(() => assertContainedDirectoryTree(tree, "runtime source"), /outside its root/u);
    rmSync(path.join(tree, "external-link"));
    assert.doesNotThrow(() => assertContainedDirectoryTree(tree, "runtime source"));
    assert.throws(
      () =>
        assertContainedDirectoryTree(tree, "packaged source", {
          allowContainedSymbolicLinks: false,
        }),
      /contains a symbolic link/u,
    );
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("copied directory trees reject contained symbolic-link cycles", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-copy-cycle-"));
  const tree = path.join(temporaryRoot, "tree");
  const left = path.join(tree, "left");
  const right = path.join(tree, "right");
  mkdirSync(left, { recursive: true });
  mkdirSync(right);
  try {
    symlinkSync(right, path.join(left, "right-link"), "dir");
    symlinkSync(left, path.join(right, "left-link"), "dir");
  } catch {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip("directory symbolic links are unavailable");
    return;
  }

  try {
    assert.throws(() => assertContainedDirectoryTree(tree, "runtime source"), /symbolic-link directory cycle/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("copied directory trees reject a filesystem root", () => {
  assert.throws(
    () => assertContainedDirectoryTree(path.parse(os.tmpdir()).root, "runtime source"),
    /must not be a filesystem root/u,
  );
});

test("copied directory trees reject non-regular entries", (context) => {
  if (process.platform === "win32") {
    context.skip("named pipes require a platform-specific fixture on Windows");
    return;
  }
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-copy-special-"));
  const tree = path.join(temporaryRoot, "tree");
  const fifo = path.join(tree, "runtime.pipe");
  mkdirSync(tree);
  const created = spawnSync("mkfifo", [fifo], { encoding: "utf8" });
  if (created.status !== 0) {
    rmSync(temporaryRoot, { force: true, recursive: true });
    context.skip(`mkfifo is unavailable: ${created.stderr || created.error || "unknown error"}`);
    return;
  }
  try {
    assert.throws(() => assertContainedDirectoryTree(tree, "packaged source"), /non-regular filesystem entry/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("copied directory trees reject non-portable descendant names", (context) => {
  if (process.platform === "win32") {
    context.skip("Windows cannot create the invalid fixture names");
    return;
  }
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-copy-names-"));
  const tree = path.join(temporaryRoot, "tree");
  mkdirSync(tree);
  try {
    writeFileSync(path.join(tree, "CON.txt"), "invalid");
    assert.throws(() => assertContainedDirectoryTree(tree, "packaged source"), /non-portable/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("copied directory trees reject case-folding collisions", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-copy-collisions-"));
  const tree = path.join(temporaryRoot, "tree");
  mkdirSync(tree);
  try {
    writeFileSync(path.join(tree, "Theme.json"), "first");
    try {
      writeFileSync(path.join(tree, "theme.json"), "second", { flag: "wx" });
    } catch {
      context.skip("the host filesystem already prevents portable case collisions");
      return;
    }
    assert.throws(() => assertContainedDirectoryTree(tree, "packaged source"), /filename collision/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("native source trees may defer portable collision checks until after explicit pruning", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-native-source-collisions-"));
  const tree = path.join(temporaryRoot, "tree");
  mkdirSync(tree);
  try {
    writeFileSync(path.join(tree, "2621A"), "first");
    try {
      writeFileSync(path.join(tree, "2621a"), "second", { flag: "wx" });
    } catch {
      context.skip("the host filesystem already prevents portable case collisions");
      return;
    }
    assert.doesNotThrow(() =>
      assertContainedDirectoryTree(tree, "native archive source", {
        allowPortableNameCollisions: true,
      }),
    );
    assert.throws(() => assertContainedDirectoryTree(tree, "prepared runtime"), /filename collision/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("copied directory trees reject Unicode-normalization collisions", (context) => {
  const temporaryRoot = mkdtempSync(path.join(os.tmpdir(), "shinsekai-copy-unicode-collisions-"));
  const tree = path.join(temporaryRoot, "tree");
  mkdirSync(tree);
  try {
    writeFileSync(path.join(tree, "\u00e9.txt"), "first");
    try {
      writeFileSync(path.join(tree, "e\u0301.txt"), "second", { flag: "wx" });
    } catch {
      context.skip("the host filesystem already normalizes Unicode filenames");
      return;
    }
    assert.throws(() => assertContainedDirectoryTree(tree, "packaged source"), /filename collision/u);
  } finally {
    rmSync(temporaryRoot, { force: true, recursive: true });
  }
});

test("exact absolute paths accept Unicode while rejecting lexical aliases", () => {
  const unicodePath = path.join(os.tmpdir(), "项目 データ", "runtime");
  assert.equal(resolveExactAbsolutePath(unicodePath), path.resolve(unicodePath));
  assert.throws(() =>
    resolveExactAbsolutePath(`${path.dirname(unicodePath)}${path.sep}.${path.sep}${path.basename(unicodePath)}`),
  );
  for (const component of [
    "CON",
    "NUL.txt",
    "CLOCK$",
    "CONIN$.log",
    "CONOUT$",
    "COM¹",
    "LPT³.txt",
    " leading",
    "trailing.",
    "trailing ",
    "alternate:stream",
  ]) {
    assert.throws(() => resolveExactAbsolutePath(path.join(os.tmpdir(), component)));
  }
  if (process.platform !== "win32") {
    assert.throws(() => resolveExactAbsolutePath(`${os.tmpdir()}/literal\\name`), /non-portable/u);
    assert.throws(() => resolveExactAbsolutePath(String.raw`\\?\C:\runtime`), /non-native Windows verbatim/u);
  } else {
    const nativePath = path.resolve(os.tmpdir(), "项目 データ", "runtime");
    if (/^[A-Za-z]:\\/u.test(nativePath)) {
      const verbatimPath = `\\\\?\\${nativePath}`;
      assert.equal(resolveExactAbsolutePath(verbatimPath), path.resolve(verbatimPath));
    }
    const verbatimUnc = String.raw`\\?\UNC\server\share\项目\runtime`;
    assert.equal(resolveExactAbsolutePath(verbatimUnc), path.resolve(verbatimUnc));
  }
  assert.throws(
    () => resolveExactAbsolutePath(String.raw`\\?\GLOBALROOT\Device\HarddiskVolume1`),
    /verbatim|device namespace/u,
  );
});

test("tracked relative paths cannot escape or change identity across platforms", () => {
  const root = path.join(os.tmpdir(), "shinsekai-relative-root");

  assert.equal(
    resolveExactRelativePath(root, "requirements/runtime-core.txt"),
    path.join(root, "requirements", "runtime-core.txt"),
  );
  for (const value of [
    "",
    "../outside",
    "./runtime",
    "runtime//python",
    "/absolute",
    "C:drive-relative",
    "~/runtime",
    "~another/runtime",
    "CON/file.txt",
    "runtime/trailing.",
  ]) {
    assert.throws(() => resolveExactRelativePath(root, value));
  }
});

test("archive members and links cannot escape or change identity during extraction", () => {
  assert.equal(validateExactArchiveMemberPath("python/Lib/module.py"), "python/Lib/module.py");
  assert.equal(validateExactArchiveMemberPath("python/Lib/"), "python/Lib");
  assert.equal(validateArchiveLinkTarget("python/bin/python", "../lib/python3.10"), "python/lib/python3.10");

  for (const value of ["/absolute", "../outside", "python/../outside", "python//module.py", "python/NUL"]) {
    assert.throws(() => validateExactArchiveMemberPath(value));
  }
  assert.throws(() => validateArchiveLinkTarget("python/bin/python", "../../../outside"), /escapes/u);
  assert.throws(() => validateArchiveLinkTarget("python/bin/python", "/outside"), /relative/u);
  assert.throws(() =>
    validateArchiveLinkTarget("python/bin/python", "NUL", {
      hardLink: true,
    }),
  );
});

test("archive member sets reject duplicate and cross-platform-colliding identities", () => {
  assert.doesNotThrow(() =>
    validateArchiveMemberSet([
      { isDirectory: true, path: "python/" },
      { isDirectory: true, path: "python/Lib/" },
      { isDirectory: false, path: "python/Lib/module.py" },
    ]),
  );

  for (const entries of [
    [
      { isDirectory: false, path: "python/module.py" },
      { isDirectory: false, path: "python/module.py" },
    ],
    [
      { isDirectory: false, path: "python/Module.py" },
      { isDirectory: false, path: "python/module.py" },
    ],
    [
      { isDirectory: false, path: "python/caf\u00e9.py" },
      { isDirectory: false, path: "python/cafe\u0301.py" },
    ],
    [
      { isDirectory: false, path: "python/lib" },
      { isDirectory: false, path: "python/lib/module.py" },
    ],
    [
      { isDirectory: false, path: "python/lib/module.py" },
      { isDirectory: false, path: "python/lib" },
    ],
  ]) {
    assert.throws(() => validateArchiveMemberSet(entries));
  }
});

test("frontend bridge launch scripts never override the project root with a cwd-relative path", () => {
  const manifest = JSON.parse(readFileSync(path.join(frontendDirectory, "package.json"), "utf8"));
  for (const name of ["dev:bridge", "dev:bridge:conda"]) {
    const command = String(manifest.scripts?.[name] ?? "");
    assert.ok(command.includes("../frontend_bridge.py"), `${name} must launch the source-owned bridge`);
    assert.doesNotMatch(command, /--project-root(?:=|\s+)\.{1,2}(?:\/|\s|$)/u);
  }
  for (const relativePath of [".github/workflows/tauri-desktop.yml", "frontend/README.md"]) {
    const content = readFileSync(path.join(repositoryDirectory, relativePath), "utf8");
    assert.doesNotMatch(content, /--project-root(?:=|\s+)\.{1,2}(?:\/|\s|$)/u);
  }
});

test("Vite converts file URLs to native paths instead of retaining URL escapes", () => {
  const config = readFileSync(path.join(frontendDirectory, "vite.config.ts"), "utf8");
  assert.match(config, /fileURLToPath\(new URL\(relativePath, import\.meta\.url\)\)/u);
  assert.match(config, /root:\s*modulePath\("\."\)/u);
  assert.doesNotMatch(config, /import\.meta\.url\)\.pathname/u);
});
