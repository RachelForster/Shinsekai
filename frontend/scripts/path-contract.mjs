import { createHash, randomUUID } from "node:crypto";
import { constants, lstatSync, readdirSync, realpathSync, statSync } from "node:fs";
import { link, open, rename, rm } from "node:fs/promises";
import path from "node:path";

const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001f\u007f\ud800-\udfff]/u;
const MAX_PORTABLE_COMPONENT_UTF8_BYTES = 255;
const WINDOWS_RESERVED_NAMES = new Set([
  "CON",
  "PRN",
  "AUX",
  "NUL",
  "CLOCK$",
  "CONIN$",
  "CONOUT$",
  ...Array.from({ length: 9 }, (_, index) => `COM${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `LPT${index + 1}`),
  "COM¹",
  "COM²",
  "COM³",
  "LPT¹",
  "LPT²",
  "LPT³",
]);

export function resolveAbsoluteEnvironmentPath(name, fallbackPath) {
  if (!Object.prototype.hasOwnProperty.call(process.env, name)) {
    return resolveExactAbsolutePath(fallbackPath, `${name} fallback`);
  }
  return resolveExactAbsolutePath(process.env[name] ?? "", name);
}

export function resolveExactAbsolutePath(rawValue, field = "path") {
  const raw = String(rawValue);
  if (!raw || raw !== raw.trim() || CONTROL_CHARACTER_PATTERN.test(raw)) {
    throw new Error(`${field} is empty or contains surrounding whitespace or control characters`);
  }

  const portable = raw.replaceAll("\\", "/");
  if (portable.startsWith("//./") || portable.startsWith("/??/")) {
    throw new Error(`${field} uses an unsupported Windows device namespace`);
  }
  let validationPath = portable;
  if (portable.startsWith("//?/")) {
    if (process.platform !== "win32") {
      throw new Error(`${field} uses non-native Windows verbatim syntax`);
    }
    const namespaceTail = portable.slice("//?/".length);
    if (/^[A-Za-z]:\//u.test(namespaceTail)) {
      validationPath = namespaceTail;
    } else if (/^UNC\//iu.test(namespaceTail)) {
      validationPath = `//${namespaceTail.slice("UNC/".length)}`;
    } else {
      throw new Error(`${field} uses an unsupported Windows verbatim namespace`);
    }
  }
  if (!path.isAbsolute(raw)) {
    throw new Error(`${field} must be an absolute path`);
  }
  if (process.platform !== "win32" && raw.startsWith("/") && raw.includes("\\")) {
    throw new Error(`${field} contains a non-portable path component`);
  }

  let components;
  if (/^[A-Za-z]:\//u.test(validationPath)) {
    const tail = validationPath.slice(3);
    components = tail ? tail.split("/") : [];
  } else if (validationPath.startsWith("//")) {
    if (process.platform !== "win32") {
      throw new Error(`${field} uses non-native UNC syntax`);
    }
    const parts = validationPath.slice(2).split("/");
    if (parts.length < 2 || !parts[0] || !parts[1]) {
      throw new Error(`${field} uses invalid UNC syntax`);
    }
    components = parts.length === 3 && parts[2] === "" ? parts.slice(0, 2) : parts;
  } else if (validationPath.startsWith("/")) {
    if (process.platform === "win32") {
      throw new Error(`${field} uses a current-drive-relative rooted path`);
    }
    const tail = validationPath.slice(1);
    components = tail ? tail.split("/") : [];
  } else {
    throw new Error(`${field} must be an absolute path`);
  }

  if (components.some((component) => component === "" || component === "." || component === "..")) {
    throw new Error(`${field} must not contain lexical path aliases`);
  }
  for (const component of components) {
    assertPortablePathComponent(component, field);
  }
  return path.resolve(raw);
}

export function resolveExactRelativePath(rootPath, rawValue, field = "relative path") {
  const raw = String(rawValue);
  if (!raw || raw !== raw.trim() || CONTROL_CHARACTER_PATTERN.test(raw)) {
    throw new Error(`${field} is empty or contains surrounding whitespace or control characters`);
  }
  const portable = raw.replaceAll("\\", "/");
  if (portable.startsWith("/") || /^[A-Za-z]:/u.test(portable) || portable.startsWith("//") || path.isAbsolute(raw)) {
    throw new Error(`${field} must be relative`);
  }
  const components = portable.split("/");
  if (components.some((component) => component === "" || component === "." || component === "..")) {
    throw new Error(`${field} must use exact relative components`);
  }
  if (components[0].startsWith("~")) {
    throw new Error(`${field} must not use a user-home alias`);
  }
  for (const component of components) {
    assertPortablePathComponent(component, field);
  }
  const root = resolveExactAbsolutePath(rootPath, `${field} root`);
  return path.join(root, ...components);
}

export function validateExactArchiveMemberPath(rawValue, field = "archive member") {
  const raw = String(rawValue);
  if (!raw || raw !== raw.trim() || CONTROL_CHARACTER_PATTERN.test(raw)) {
    throw new Error(`${field} is empty or contains surrounding whitespace or control characters`);
  }
  const portable = raw.replaceAll("\\", "/");
  const withoutDirectoryMarker = portable.endsWith("/") ? portable.slice(0, -1) : portable;
  if (!withoutDirectoryMarker || withoutDirectoryMarker.startsWith("/") || /^[A-Za-z]:/u.test(withoutDirectoryMarker)) {
    throw new Error(`${field} must be relative`);
  }
  const components = withoutDirectoryMarker.split("/");
  if (components.some((component) => component === "" || component === "." || component === "..")) {
    throw new Error(`${field} must use exact relative components`);
  }
  if (components[0].startsWith("~")) {
    throw new Error(`${field} must not use a user-home alias`);
  }
  for (const component of components) {
    assertPortablePathComponent(component, field);
  }
  return components.join("/");
}

export function validateArchiveMemberSet(entries, field = "archive") {
  const entryTypes = new Map();
  const prefixSpellings = new Map();

  for (const entry of entries) {
    const normalized = validateExactArchiveMemberPath(entry.path, `${field} member`);
    const parts = normalized.split("/");
    const folded = parts.map((component) => portableNameKey(component));
    const foldedPath = folded.join("/");

    for (let index = 1; index <= folded.length; index += 1) {
      const prefixKey = folded.slice(0, index).join("/");
      const spelling = parts.slice(0, index).join("/");
      const previous = prefixSpellings.get(prefixKey);
      if (previous !== undefined && previous !== spelling) {
        throw new Error(
          `${field} contains paths that collide by case or Unicode normalization: ${JSON.stringify(entry.path)}`,
        );
      }
      prefixSpellings.set(prefixKey, spelling);
    }

    if (entryTypes.has(foldedPath)) {
      throw new Error(`${field} contains a duplicate portable path: ${JSON.stringify(entry.path)}`);
    }
    for (let index = 1; index < folded.length; index += 1) {
      if (entryTypes.get(folded.slice(0, index).join("/")) === "file") {
        throw new Error(`${field} contains a path nested below a file: ${JSON.stringify(entry.path)}`);
      }
    }
    if (
      !entry.isDirectory &&
      [...entryTypes.keys()].some(
        (existing) => existing.length > foldedPath.length && existing.startsWith(`${foldedPath}/`),
      )
    ) {
      throw new Error(`${field} contains a file that conflicts with a directory: ${JSON.stringify(entry.path)}`);
    }
    entryTypes.set(foldedPath, entry.isDirectory ? "directory" : "file");
  }

  if (![...entryTypes.values()].some((entryType) => entryType === "file")) {
    throw new Error(`${field} contains no regular file-shaped entries`);
  }
}

export function validateArchiveLinkTarget(
  memberValue,
  targetValue,
  { field = "archive link target", hardLink = false } = {},
) {
  const member = validateExactArchiveMemberPath(memberValue, "archive link member");
  const rawTarget = String(targetValue);
  if (!rawTarget || rawTarget !== rawTarget.trim() || CONTROL_CHARACTER_PATTERN.test(rawTarget)) {
    throw new Error(`${field} is empty or contains surrounding whitespace or control characters`);
  }
  const portableTarget = rawTarget.replaceAll("\\", "/");
  if (
    portableTarget.startsWith("/") ||
    /^[A-Za-z]:/u.test(portableTarget) ||
    portableTarget.split("/", 1)[0].startsWith("~")
  ) {
    throw new Error(`${field} must be relative`);
  }

  const resolved = hardLink ? [] : member.split("/").slice(0, -1);
  for (const component of portableTarget.split("/")) {
    if (!component || component === ".") {
      throw new Error(`${field} must use exact path components`);
    }
    if (component === "..") {
      if (resolved.length === 0) {
        throw new Error(`${field} escapes the archive root`);
      }
      resolved.pop();
      continue;
    }
    assertPortablePathComponent(component, field);
    resolved.push(component);
  }
  return resolved.join("/");
}

export function assertSafeMutableDirectory(
  candidatePath,
  { field = "mutable directory", protectedRoots = [], allowedRoots = [] } = {},
) {
  const candidate = resolveExactAbsolutePath(candidatePath, field);
  if (samePath(candidate, path.parse(candidate).root)) {
    throw new Error(`${field} must not be a filesystem root`);
  }
  assertNoExistingSymbolicLinkComponents(candidate, field);
  const metadata = lstatIfExists(candidate);
  if (metadata !== null && (!metadata.isDirectory() || metadata.isSymbolicLink())) {
    throw new Error(`${field} must be a regular non-link directory`);
  }

  for (const protectedRootValue of protectedRoots) {
    const protectedRoot = resolveExactAbsolutePath(protectedRootValue, `${field} protected root`);
    if (isSameOrWithin(protectedRoot, candidate)) {
      throw new Error(`${field} must not be the same as or contain protected root ${protectedRoot}`);
    }
    if (
      isSameOrWithin(candidate, protectedRoot) &&
      !allowedRoots.some((allowedRoot) =>
        isSameOrWithin(candidate, resolveExactAbsolutePath(allowedRoot, `${field} allowed root`)),
      )
    ) {
      throw new Error(`${field} is inside a protected root but outside its managed storage`);
    }
  }
  return candidate;
}

export function assertRegularFileWithoutLinks(candidatePath, field = "file") {
  const candidate = resolveExactAbsolutePath(candidatePath, field);
  if (samePath(candidate, path.parse(candidate).root)) {
    throw new Error(`${field} must not be a filesystem root`);
  }
  assertNoExistingSymbolicLinkComponents(candidate, field);
  const metadata = lstatIfExists(candidate);
  if (!metadata?.isFile() || metadata.isSymbolicLink()) {
    throw new Error(`${field} must be a regular non-link file`);
  }
  return candidate;
}

export function captureExecutableSnapshot(
  commandValue,
  { field = "executable", searchPath = process.env.PATH, pathExtensions = process.env.PATHEXT } = {},
) {
  const command = String(commandValue);
  if (!command || command !== command.trim() || CONTROL_CHARACTER_PATTERN.test(command)) {
    throw new Error(`${field} name is empty or contains surrounding whitespace or control characters`);
  }

  if (path.isAbsolute(command)) {
    return captureExecutableCandidate(resolveExactAbsolutePath(command, field), field);
  }
  if (path.basename(command) !== command) {
    throw new Error(`${field} must be an absolute path or one portable PATH name`);
  }
  assertPortablePathComponent(command, field);
  if (searchPath === undefined || searchPath === null) {
    throw new Error(`${field} cannot be resolved because PATH is not configured`);
  }

  let lastError = null;
  for (const rawDirectory of String(searchPath).split(path.delimiter)) {
    if (!rawDirectory || !path.isAbsolute(rawDirectory)) {
      continue;
    }
    let directory;
    try {
      directory = resolveExactAbsolutePath(rawDirectory, `${field} PATH directory`);
    } catch (error) {
      lastError = error;
      continue;
    }
    for (const name of executableCandidateNames(command, pathExtensions)) {
      const candidate = path.join(directory, name);
      if (lstatIfExists(candidate) === null) {
        continue;
      }
      try {
        return captureExecutableCandidate(candidate, field);
      } catch (error) {
        lastError = error;
      }
    }
  }
  throw new Error(
    `${field} ${JSON.stringify(command)} was not found in deterministic PATH entries${
      lastError ? `: ${lastError.message}` : ""
    }`,
  );
}

export function captureRegularFileAliasSnapshot(candidateValue, field = "file") {
  return captureStableAliasSnapshot(candidateValue, field, "file");
}

export function captureDirectoryAliasSnapshot(candidateValue, field = "directory") {
  return captureStableAliasSnapshot(candidateValue, field, "directory");
}

export function requireRegularFileSnapshot(snapshot, field = "file") {
  return requireStableAliasSnapshot(snapshot, field, "file");
}

export function requireDirectorySnapshot(snapshot, field = "directory") {
  return requireStableAliasSnapshot(snapshot, field, "directory");
}

export function requireExecutableSnapshot(snapshot, field = "executable") {
  if (
    snapshot === null ||
    typeof snapshot !== "object" ||
    typeof snapshot.path !== "string" ||
    snapshot.identity === undefined ||
    snapshot.parentIdentity === undefined
  ) {
    throw new Error(`${field} snapshot is invalid`);
  }
  const executable = assertRegularFileWithoutLinks(snapshot.path, field);
  const parent = path.dirname(executable);
  const currentParentIdentity = assertDirectoryIdentity(parent, `${field} parent`);
  const currentIdentity = lstatIfExists(executable);
  if (
    !sameFilesystemIdentity(snapshot.parentIdentity, currentParentIdentity) ||
    currentIdentity === null ||
    !sameStableFileIdentity(snapshot.identity, currentIdentity)
  ) {
    throw new Error(`${field} identity changed`);
  }
  assertExecutablePermissions(currentIdentity, field);
  return executable;
}

export async function readRegularFileWithoutLinks(
  candidatePath,
  { field = "file read", encoding = null, expectedIdentity = undefined, expectedParentIdentity = undefined } = {},
) {
  return withOpenRegularFileWithoutLinks(
    candidatePath,
    {
      field,
      expectedIdentity,
      expectedParentIdentity,
    },
    async (handle) => {
      const data = encoding === null ? await handle.readFile() : await handle.readFile({ encoding });
      return { data };
    },
  );
}

export async function sha256RegularFileWithoutLinks(
  candidatePath,
  {
    field = "file hash",
    expectedIdentity = undefined,
    expectedParentIdentity = undefined,
    expectedSha256 = undefined,
  } = {},
) {
  return withOpenRegularFileWithoutLinks(
    candidatePath,
    {
      field,
      expectedIdentity,
      expectedParentIdentity,
    },
    async (handle) => {
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
      const sha256 = hash.digest("hex");
      if (expectedSha256 !== undefined && sha256 !== String(expectedSha256).toLowerCase()) {
        throw new Error(`${field} content changed`);
      }
      return { sha256 };
    },
  );
}

export async function copyRegularFileExclusiveWithoutLinks(
  sourcePath,
  destinationPath,
  {
    field = "file copy",
    expectedSourceIdentity = undefined,
    expectedSourceParentIdentity = undefined,
    expectedDestinationParentIdentity = undefined,
    expectedSha256 = undefined,
  } = {},
) {
  const source = resolveExactAbsolutePath(sourcePath, `${field} source`);
  const destination = resolveExactAbsolutePath(destinationPath, `${field} destination`);
  if (samePath(source, destination)) {
    throw new Error(`${field} source and destination must differ`);
  }
  const destinationParent = path.dirname(destination);
  const destinationParentIdentity = assertDirectoryIdentity(destinationParent, `${field} destination parent`);
  if (
    expectedDestinationParentIdentity !== undefined &&
    !sameFilesystemIdentity(expectedDestinationParentIdentity, destinationParentIdentity)
  ) {
    throw new Error(`${field} destination parent identity changed`);
  }
  assertNoExistingSymbolicLinkComponents(destination, `${field} destination`);
  if (lstatIfExists(destination) !== null) {
    throw new Error(`${field} destination already exists`);
  }
  assertPortableSiblingNameAvailable(destinationParent, path.basename(destination), field);

  let destinationIdentity = null;
  try {
    const copied = await withOpenRegularFileWithoutLinks(
      source,
      {
        field: `${field} source`,
        expectedIdentity: expectedSourceIdentity,
        expectedParentIdentity: expectedSourceParentIdentity,
      },
      async (sourceHandle) => {
        assertSameDirectoryIdentity(destinationParent, destinationParentIdentity, `${field} destination parent`);
        const destinationHandle = await open(
          destination,
          constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0),
          0o600,
        );
        try {
          const createdDestinationIdentity = await destinationHandle.stat({
            bigint: true,
          });
          if (!createdDestinationIdentity.isFile() || createdDestinationIdentity.isSymbolicLink()) {
            throw new Error(`${field} destination is not a regular file`);
          }
          destinationIdentity = createdDestinationIdentity;
          assertStableOpenFileIdentity(
            destination,
            createdDestinationIdentity,
            createdDestinationIdentity,
            `${field} destination`,
          );

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
                throw new Error(`${field} destination write made no progress`);
              }
              written += result.bytesWritten;
            }
            position += bytesRead;
          }

          const sha256 = hash.digest("hex");
          if (expectedSha256 !== undefined && sha256 !== String(expectedSha256).toLowerCase()) {
            throw new Error(`${field} source content changed`);
          }
          await destinationHandle.sync();
          const finalDestinationIdentity = await destinationHandle.stat({
            bigint: true,
          });
          if (!sameFilesystemIdentity(createdDestinationIdentity, finalDestinationIdentity)) {
            throw new Error(`${field} destination identity changed`);
          }
          destinationIdentity = finalDestinationIdentity;
          assertStableOpenFileIdentity(
            destination,
            finalDestinationIdentity,
            finalDestinationIdentity,
            `${field} destination`,
          );
          assertSameDirectoryIdentity(destinationParent, destinationParentIdentity, `${field} destination parent`);
          return {
            destinationIdentity,
            destinationParentIdentity,
            sha256,
          };
        } finally {
          await destinationHandle.close();
        }
      },
    );
    return {
      ...copied,
      sourceIdentity: copied.identity,
      sourceParentIdentity: copied.parentIdentity,
    };
  } catch (error) {
    if (destinationIdentity !== null) {
      try {
        await removeFileWithoutLinks(destination, {
          expectedIdentity: destinationIdentity,
          expectedParentIdentity: destinationParentIdentity,
          field: `${field} failed destination cleanup`,
          missingOk: true,
        });
      } catch {
        // Preserve a replacement path or parent. The caller can safely clean
        // its private destination tree using the identities it already owns.
      }
    }
    throw error;
  }
}

async function withOpenRegularFileWithoutLinks(
  candidatePath,
  { field, expectedIdentity, expectedParentIdentity },
  operation,
) {
  const candidate = assertRegularFileWithoutLinks(candidatePath, field);
  const parent = path.dirname(candidate);
  const parentIdentity = assertDirectoryIdentity(parent, `${field} parent`);
  if (expectedParentIdentity !== undefined && !sameFilesystemIdentity(expectedParentIdentity, parentIdentity)) {
    throw new Error(`${field} parent identity changed`);
  }

  const handle = await open(candidate, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const identity = await handle.stat({ bigint: true });
    assertStableOpenFileIdentity(candidate, identity, identity, field);
    if (expectedIdentity !== undefined && !sameStableFileIdentity(expectedIdentity, identity)) {
      throw new Error(`${field} identity changed`);
    }
    assertSameDirectoryIdentity(parent, parentIdentity, `${field} parent`);

    const result = await operation(handle);

    const finalIdentity = await handle.stat({ bigint: true });
    if (!sameStableFileIdentity(identity, finalIdentity)) {
      throw new Error(`${field} changed while open`);
    }
    assertStableOpenFileIdentity(candidate, identity, finalIdentity, field);
    assertSameDirectoryIdentity(parent, parentIdentity, `${field} parent`);
    return { ...result, identity, parentIdentity };
  } finally {
    await handle.close();
  }
}

function assertStableOpenFileIdentity(candidate, expectedIdentity, openedIdentity, field) {
  const currentIdentity = lstatIfExists(candidate);
  if (
    !openedIdentity.isFile() ||
    openedIdentity.isSymbolicLink() ||
    !currentIdentity?.isFile() ||
    currentIdentity.isSymbolicLink() ||
    !sameStableFileIdentity(expectedIdentity, openedIdentity) ||
    !sameStableFileIdentity(expectedIdentity, currentIdentity)
  ) {
    throw new Error(`${field} identity changed`);
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

export function assertNonOverlappingDirectories(entries) {
  for (let leftIndex = 0; leftIndex < entries.length; leftIndex += 1) {
    const left = {
      ...entries[leftIndex],
      path: resolveExactAbsolutePath(entries[leftIndex].path, entries[leftIndex].field),
    };
    for (let rightIndex = leftIndex + 1; rightIndex < entries.length; rightIndex += 1) {
      const right = {
        ...entries[rightIndex],
        path: resolveExactAbsolutePath(entries[rightIndex].path, entries[rightIndex].field),
      };
      if (isSameOrWithin(left.path, right.path) || isSameOrWithin(right.path, left.path)) {
        throw new Error(`${left.field} and ${right.field} must not overlap`);
      }
    }
  }
}

export function assertContainedDirectoryTree(
  rootPath,
  field = "directory tree",
  { allowContainedSymbolicLinks = true, allowPortableNameCollisions = false } = {},
) {
  const root = resolveExactAbsolutePath(rootPath, field);
  if (samePath(root, path.parse(root).root)) {
    throw new Error(`${field} must not be a filesystem root`);
  }
  assertNoExistingSymbolicLinkComponents(root, field);
  const canonicalRoot = realpathSync.native(root);
  const directoryGraph = new Map();

  const addDirectoryEdge = (from, to) => {
    let edges = directoryGraph.get(from);
    if (edges === undefined) {
      edges = new Set();
      directoryGraph.set(from, edges);
    }
    edges.add(to);
    if (!directoryGraph.has(to)) {
      directoryGraph.set(to, new Set());
    }
  };

  const walk = (directory) => {
    const canonicalDirectory = realpathSync.native(directory);
    if (!directoryGraph.has(canonicalDirectory)) {
      directoryGraph.set(canonicalDirectory, new Set());
    }
    const entries = readdirSync(directory, { withFileTypes: true });
    const portableNames = new Map();
    for (const entry of entries) {
      assertPortablePathComponent(entry.name, field);
      const portableKey = portableNameKey(entry.name);
      const previous = portableNames.get(portableKey);
      if (!allowPortableNameCollisions && previous !== undefined && previous !== entry.name) {
        throw new Error(
          `${field} contains a portable filename collision: ${JSON.stringify(entry.name)} conflicts with ${JSON.stringify(previous)}`,
        );
      }
      portableNames.set(portableKey, entry.name);

      const entryPath = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) {
        if (!allowContainedSymbolicLinks) {
          throw new Error(`${field} contains a symbolic link: ${entryPath}`);
        }
        const target = realpathSync.native(entryPath);
        if (!isSameOrWithin(target, canonicalRoot)) {
          throw new Error(`${field} contains a symbolic link outside its root: ${entryPath}`);
        }
        if (statSync(entryPath).isDirectory()) {
          addDirectoryEdge(canonicalDirectory, target);
        }
      } else if (entry.isDirectory()) {
        addDirectoryEdge(canonicalDirectory, realpathSync.native(entryPath));
        walk(entryPath);
      } else if (!entry.isFile()) {
        throw new Error(`${field} contains a non-regular filesystem entry: ${entryPath}`);
      }
    }
  };

  walk(root);
  assertAcyclicDirectoryGraph(directoryGraph, canonicalRoot, field);
  return root;
}

function assertAcyclicDirectoryGraph(graph, root, field) {
  const visiting = new Set();
  const visited = new Set();

  const visit = (directory) => {
    if (visiting.has(directory)) {
      throw new Error(`${field} contains a symbolic-link directory cycle at ${directory}`);
    }
    if (visited.has(directory)) {
      return;
    }
    visiting.add(directory);
    for (const child of graph.get(directory) ?? []) {
      visit(child);
    }
    visiting.delete(directory);
    visited.add(directory);
  };

  visit(root);
}

export async function removeDirectoryWithoutLinks(
  targetPath,
  { field = "directory removal", expectedIdentity = null, expectedParentIdentity = undefined, missingOk = false } = {},
) {
  const target = resolveExactAbsolutePath(targetPath, `${field} target`);
  const parent = path.dirname(target);
  const parentMetadata = assertDirectoryIdentity(parent, `${field} parent`);
  if (expectedParentIdentity !== undefined && !sameFilesystemIdentity(expectedParentIdentity, parentMetadata)) {
    throw new Error(`${field} parent identity changed`);
  }
  assertNoExistingSymbolicLinkComponents(target, `${field} target`);
  const targetMetadata = lstatIfExists(target);
  if (targetMetadata === null) {
    if (missingOk) {
      return;
    }
    throw new Error(`${field} target does not exist`);
  }
  if (!targetMetadata.isDirectory() || targetMetadata.isSymbolicLink()) {
    throw new Error(`${field} target must be a regular non-link directory`);
  }
  if (expectedIdentity !== null && !sameFilesystemIdentity(expectedIdentity, targetMetadata)) {
    throw new Error(`${field} target identity changed`);
  }

  const trash = portableSiblingPath(target, `.delete-${randomUUID()}`, `${field} staging directory`);
  assertNoExistingSymbolicLinkComponents(trash, `${field} staging directory`);
  if (lstatIfExists(trash) !== null) {
    throw new Error(`${field} staging directory already exists`);
  }
  assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
  await rename(target, trash);
  try {
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    assertNoExistingSymbolicLinkComponents(trash, `${field} staging directory`);
    const trashMetadata = lstatIfExists(trash);
    if (
      !trashMetadata?.isDirectory() ||
      trashMetadata.isSymbolicLink() ||
      !sameFilesystemIdentity(targetMetadata, trashMetadata)
    ) {
      throw new Error(`${field} target changed before cleanup`);
    }
    await rm(trash, { recursive: true });
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
  } catch (error) {
    const trashMetadata = lstatIfExists(trash);
    if (lstatIfExists(target) === null && trashMetadata !== null) {
      assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
      await rename(trash, target);
      assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    }
    throw error;
  }
}

export async function removeFileWithoutLinks(
  targetPath,
  { field = "file removal", expectedIdentity = null, expectedParentIdentity = undefined, missingOk = false } = {},
) {
  const target = resolveExactAbsolutePath(targetPath, `${field} target`);
  const parent = path.dirname(target);
  const parentMetadata = assertDirectoryIdentity(parent, `${field} parent`);
  if (expectedParentIdentity !== undefined && !sameFilesystemIdentity(expectedParentIdentity, parentMetadata)) {
    throw new Error(`${field} parent identity changed`);
  }
  assertNoExistingSymbolicLinkComponents(target, `${field} target`);
  const targetMetadata = lstatIfExists(target);
  if (targetMetadata === null) {
    if (missingOk) {
      return;
    }
    throw new Error(`${field} target does not exist`);
  }
  if (!targetMetadata.isFile() || targetMetadata.isSymbolicLink()) {
    throw new Error(`${field} target must be a regular non-link file`);
  }
  if (expectedIdentity !== null && !sameFilesystemIdentity(expectedIdentity, targetMetadata)) {
    throw new Error(`${field} target identity changed`);
  }

  const trash = portableSiblingPath(target, `.delete-${randomUUID()}`, `${field} staging file`);
  assertNoExistingSymbolicLinkComponents(trash, `${field} staging file`);
  if (lstatIfExists(trash) !== null) {
    throw new Error(`${field} staging file already exists`);
  }
  assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
  await rename(target, trash);
  try {
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    assertNoExistingSymbolicLinkComponents(trash, `${field} staging file`);
    const trashMetadata = lstatIfExists(trash);
    if (
      !trashMetadata?.isFile() ||
      trashMetadata.isSymbolicLink() ||
      !sameFilesystemIdentity(targetMetadata, trashMetadata)
    ) {
      throw new Error(`${field} target changed before cleanup`);
    }
    await rm(trash, { force: true });
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
  } catch (error) {
    const trashMetadata = lstatIfExists(trash);
    if (lstatIfExists(target) === null && trashMetadata !== null) {
      assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
      await rename(trash, target);
      assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    }
    throw error;
  }
}

export async function replaceDirectoryTransactionally(
  stagingPath,
  destinationPath,
  {
    field = "directory publication",
    expectedStagingIdentity = undefined,
    expectedDestinationIdentity = undefined,
    expectedParentIdentity = undefined,
  } = {},
) {
  const staging = resolveExactAbsolutePath(stagingPath, `${field} staging directory`);
  const destination = resolveExactAbsolutePath(destinationPath, `${field} destination directory`);
  if (samePath(staging, destination)) {
    throw new Error(`${field} staging and destination directories must differ`);
  }
  if (!samePath(path.dirname(staging), path.dirname(destination))) {
    throw new Error(`${field} staging and destination directories must share a parent`);
  }
  const parent = path.dirname(destination);
  const parentMetadata = assertDirectoryIdentity(parent, `${field} parent`);
  if (expectedParentIdentity !== undefined && !sameFilesystemIdentity(expectedParentIdentity, parentMetadata)) {
    throw new Error(`${field} parent identity changed`);
  }

  assertNoExistingSymbolicLinkComponents(staging, `${field} staging directory`);
  const stagingMetadata = lstatIfExists(staging);
  if (!stagingMetadata?.isDirectory() || stagingMetadata.isSymbolicLink()) {
    throw new Error(`${field} staging path must be a regular non-link directory`);
  }
  if (expectedStagingIdentity !== undefined && !sameFilesystemIdentity(expectedStagingIdentity, stagingMetadata)) {
    throw new Error(`${field} staging directory identity changed`);
  }
  assertContainedDirectoryTree(staging, `${field} staging tree`, {
    allowContainedSymbolicLinks: false,
  });

  assertNoExistingSymbolicLinkComponents(destination, `${field} destination directory`);
  const destinationMetadata = lstatIfExists(destination);
  if (destinationMetadata !== null && (!destinationMetadata.isDirectory() || destinationMetadata.isSymbolicLink())) {
    throw new Error(`${field} destination path must be a regular non-link directory`);
  }
  if (expectedDestinationIdentity !== undefined) {
    if (expectedDestinationIdentity === null) {
      if (destinationMetadata !== null) {
        throw new Error(`${field} destination directory appeared before publication`);
      }
    } else if (
      destinationMetadata === null ||
      !sameFilesystemIdentity(expectedDestinationIdentity, destinationMetadata)
    ) {
      throw new Error(`${field} destination directory identity changed`);
    }
  }
  assertPortableSiblingNameAvailable(path.dirname(destination), path.basename(destination), field);

  let backup = null;
  if (destinationMetadata !== null) {
    backup = portableSiblingPath(destination, `.backup-${randomUUID()}`, `${field} backup directory`);
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    await rename(destination, backup);
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    const backupMetadata = lstatIfExists(backup);
    if (
      !backupMetadata?.isDirectory() ||
      backupMetadata.isSymbolicLink() ||
      !sameFilesystemIdentity(destinationMetadata, backupMetadata)
    ) {
      if (lstatIfExists(destination) === null) {
        assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
        await rename(backup, destination);
        assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
      }
      throw new Error(`${field} destination changed before publication`);
    }
  }

  try {
    assertContainedDirectoryTree(staging, `${field} staging tree`, {
      allowContainedSymbolicLinks: false,
    });
    const currentStagingMetadata = lstatIfExists(staging);
    if (
      !currentStagingMetadata?.isDirectory() ||
      currentStagingMetadata.isSymbolicLink() ||
      !sameFilesystemIdentity(stagingMetadata, currentStagingMetadata)
    ) {
      throw new Error(`${field} staging directory identity changed`);
    }
    // Node does not expose renameat2(RENAME_NOREPLACE) for directories.
    // Recheck immediately before publication so a destination introduced
    // after the backup move is preserved instead of being knowingly replaced.
    if (lstatIfExists(destination) !== null) {
      throw new Error(`${field} destination appeared during publication`);
    }
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    await rename(staging, destination);
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    const publishedMetadata = lstatIfExists(destination);
    if (
      !publishedMetadata?.isDirectory() ||
      publishedMetadata.isSymbolicLink() ||
      !sameFilesystemIdentity(stagingMetadata, publishedMetadata)
    ) {
      throw new Error(`${field} staging directory identity changed during publication`);
    }
  } catch (error) {
    if (backup !== null && lstatIfExists(destination) === null) {
      const backupMetadata = lstatIfExists(backup);
      if (backupMetadata?.isDirectory() && !backupMetadata.isSymbolicLink()) {
        assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
        await rename(backup, destination);
        assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
        backup = null;
      }
    }
    throw error;
  }

  if (backup !== null) {
    const backupMetadata = lstatIfExists(backup);
    if (
      !backupMetadata?.isDirectory() ||
      backupMetadata.isSymbolicLink() ||
      destinationMetadata === null ||
      !sameFilesystemIdentity(destinationMetadata, backupMetadata)
    ) {
      throw new Error(`${field} backup changed before cleanup: ${backup}`);
    }
    await removeDirectoryWithoutLinks(backup, {
      expectedIdentity: destinationMetadata,
      expectedParentIdentity: parentMetadata,
      field: `${field} backup cleanup`,
    });
  }
  assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
  return destination;
}

export async function replaceFileTransactionally(
  stagingPath,
  destinationPath,
  {
    field = "file publication",
    expectedStagingIdentity = undefined,
    expectedDestinationIdentity = undefined,
    expectedParentIdentity = undefined,
  } = {},
) {
  const staging = resolveExactAbsolutePath(stagingPath, `${field} staging file`);
  const destination = resolveExactAbsolutePath(destinationPath, `${field} destination file`);
  if (samePath(staging, destination)) {
    throw new Error(`${field} staging and destination files must differ`);
  }
  if (!samePath(path.dirname(staging), path.dirname(destination))) {
    throw new Error(`${field} staging and destination files must share a parent`);
  }
  const parent = path.dirname(destination);
  const parentMetadata = assertDirectoryIdentity(parent, `${field} parent`);
  if (expectedParentIdentity !== undefined && !sameFilesystemIdentity(expectedParentIdentity, parentMetadata)) {
    throw new Error(`${field} parent identity changed`);
  }

  assertRegularFileWithoutLinks(staging, `${field} staging file`);
  const stagingMetadata = lstatIfExists(staging);
  if (stagingMetadata === null) {
    throw new Error(`${field} staging file does not exist`);
  }
  if (expectedStagingIdentity !== undefined && !sameFilesystemIdentity(expectedStagingIdentity, stagingMetadata)) {
    throw new Error(`${field} staging file identity changed`);
  }
  assertNoExistingSymbolicLinkComponents(destination, `${field} destination file`);
  const destinationMetadata = lstatIfExists(destination);
  if (destinationMetadata !== null && (!destinationMetadata.isFile() || destinationMetadata.isSymbolicLink())) {
    throw new Error(`${field} destination path must be a regular non-link file`);
  }
  if (expectedDestinationIdentity !== undefined) {
    if (expectedDestinationIdentity === null) {
      if (destinationMetadata !== null) {
        throw new Error(`${field} destination file appeared before publication`);
      }
    } else if (
      destinationMetadata === null ||
      !sameFilesystemIdentity(expectedDestinationIdentity, destinationMetadata)
    ) {
      throw new Error(`${field} destination file identity changed`);
    }
  }
  assertPortableSiblingNameAvailable(path.dirname(destination), path.basename(destination), field);

  let backup = null;
  if (destinationMetadata !== null) {
    backup = portableSiblingPath(destination, `.backup-${randomUUID()}`, `${field} backup file`);
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    await rename(destination, backup);
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    try {
      assertRegularFileWithoutLinks(backup, `${field} backup file`);
      const backupMetadata = lstatIfExists(backup);
      if (backupMetadata === null || !sameFilesystemIdentity(destinationMetadata, backupMetadata)) {
        throw new Error(`${field} destination changed before publication`);
      }
    } catch (error) {
      if (lstatIfExists(destination) === null) {
        assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
        await rename(backup, destination);
        assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
      }
      throw error;
    }
  }

  let publishedMetadata = null;
  try {
    assertRegularFileWithoutLinks(staging, `${field} staging file`);
    const currentStagingMetadata = lstatIfExists(staging);
    if (currentStagingMetadata === null || !sameFilesystemIdentity(stagingMetadata, currentStagingMetadata)) {
      throw new Error(`${field} staging file identity changed`);
    }
    if (lstatIfExists(destination) !== null) {
      throw new Error(`${field} destination changed before publication`);
    }
    // A normal POSIX rename silently replaces a destination file created
    // after the existence check. A same-volume hard link gives this file
    // publication an atomic create-if-absent step on every supported desktop
    // filesystem; the private staging name is removed only after identity
    // verification succeeds.
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    await link(staging, destination);
    assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
    publishedMetadata = lstatIfExists(destination);
    if (publishedMetadata === null || !sameFilesystemIdentity(stagingMetadata, publishedMetadata)) {
      throw new Error(`${field} staging file identity changed during publication`);
    }
    await removeFileWithoutLinks(staging, {
      expectedIdentity: stagingMetadata,
      expectedParentIdentity: parentMetadata,
      field: `${field} staging cleanup`,
    });
  } catch (error) {
    const currentPublishedMetadata = lstatIfExists(destination);
    if (
      publishedMetadata !== null &&
      currentPublishedMetadata !== null &&
      sameFilesystemIdentity(publishedMetadata, currentPublishedMetadata)
    ) {
      await removeFileWithoutLinks(destination, {
        expectedIdentity: publishedMetadata,
        expectedParentIdentity: parentMetadata,
        field: `${field} failed publication cleanup`,
      });
      publishedMetadata = null;
    }
    if (backup !== null && lstatIfExists(destination) === null) {
      assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
      await rename(backup, destination);
      assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
      backup = null;
    }
    throw error;
  }

  if (backup !== null) {
    await removeFileWithoutLinks(backup, {
      expectedIdentity: destinationMetadata,
      expectedParentIdentity: parentMetadata,
      field: `${field} backup cleanup`,
    });
  }
  assertSameDirectoryIdentity(parent, parentMetadata, `${field} parent`);
  return destination;
}

function assertPortableSiblingNameAvailable(directory, requestedName, field) {
  const requestedKey = portableNameKey(requestedName);
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.name !== requestedName && portableNameKey(entry.name) === requestedKey) {
      throw new Error(
        `${field} destination has a portable filename collision: ${JSON.stringify(requestedName)} conflicts with ${JSON.stringify(entry.name)}`,
      );
    }
  }
}

function captureExecutableCandidate(candidatePath, field) {
  const candidate = resolveExactAbsolutePath(candidatePath, field);
  const candidateParent = path.dirname(candidate);
  const candidateParentIdentity = assertDirectoryIdentity(candidateParent, `${field} selected PATH directory`);
  const candidateIdentity = lstatIfExists(candidate);
  if (candidateIdentity === null || (!candidateIdentity.isFile() && !candidateIdentity.isSymbolicLink())) {
    throw new Error(`${field} candidate must be a regular file or a leaf symbolic link`);
  }

  const canonical = resolveExactAbsolutePath(realpathSync.native(candidate), `${field} canonical path`);
  const executable = assertRegularFileWithoutLinks(canonical, `${field} canonical file`);
  const parent = path.dirname(executable);
  const parentIdentity = assertDirectoryIdentity(parent, `${field} canonical parent`);
  const identity = lstatIfExists(executable);
  if (identity === null) {
    throw new Error(`${field} canonical file disappeared`);
  }
  assertExecutablePermissions(identity, field);

  const currentCandidateParent = assertDirectoryIdentity(candidateParent, `${field} selected PATH directory`);
  const currentCanonical = resolveExactAbsolutePath(realpathSync.native(candidate), `${field} canonical path`);
  const currentIdentity = lstatIfExists(executable);
  if (
    !sameFilesystemIdentity(candidateParentIdentity, currentCandidateParent) ||
    !samePath(currentCanonical, executable) ||
    currentIdentity === null ||
    !sameStableFileIdentity(identity, currentIdentity)
  ) {
    throw new Error(`${field} changed while it was selected`);
  }
  return Object.freeze({
    path: executable,
    identity,
    parentIdentity,
  });
}

function captureStableAliasSnapshot(candidateValue, field, kind) {
  const candidate = resolveExactAbsolutePath(candidateValue, field);
  const selectedParent = path.dirname(candidate);
  const selectedParentIdentity = assertDirectoryIdentity(selectedParent, `${field} selected parent`);
  const selectedIdentity = lstatIfExists(candidate);
  const selectedTypeMatches =
    kind === "file"
      ? selectedIdentity?.isFile() || selectedIdentity?.isSymbolicLink()
      : selectedIdentity?.isDirectory() || selectedIdentity?.isSymbolicLink();
  if (!selectedTypeMatches) {
    throw new Error(`${field} must be an existing ${kind} or a leaf symbolic link`);
  }

  const canonical = resolveExactAbsolutePath(realpathSync.native(candidate), `${field} canonical path`);
  const canonicalIdentity =
    kind === "file"
      ? lstatIfExists(assertRegularFileWithoutLinks(canonical, `${field} canonical file`))
      : assertDirectoryIdentity(canonical, `${field} canonical directory`);
  if (canonicalIdentity === null) {
    throw new Error(`${field} canonical ${kind} disappeared`);
  }
  const canonicalParent = path.dirname(canonical);
  const canonicalParentIdentity = assertDirectoryIdentity(canonicalParent, `${field} canonical parent`);

  const currentSelectedParent = assertDirectoryIdentity(selectedParent, `${field} selected parent`);
  const currentCanonical = resolveExactAbsolutePath(realpathSync.native(candidate), `${field} canonical path`);
  const currentCanonicalIdentity = lstatIfExists(canonical);
  if (
    !sameFilesystemIdentity(selectedParentIdentity, currentSelectedParent) ||
    !samePath(currentCanonical, canonical) ||
    currentCanonicalIdentity === null ||
    !sameStableFileIdentity(canonicalIdentity, currentCanonicalIdentity)
  ) {
    throw new Error(`${field} alias changed while it was resolved`);
  }
  return Object.freeze({
    path: canonical,
    identity: canonicalIdentity,
    parentIdentity: canonicalParentIdentity,
  });
}

function requireStableAliasSnapshot(snapshot, field, kind) {
  if (
    snapshot === null ||
    typeof snapshot !== "object" ||
    typeof snapshot.path !== "string" ||
    snapshot.identity === undefined ||
    snapshot.parentIdentity === undefined
  ) {
    throw new Error(`${field} snapshot is invalid`);
  }
  const candidate =
    kind === "file"
      ? assertRegularFileWithoutLinks(snapshot.path, field)
      : resolveExactAbsolutePath(snapshot.path, field);
  const parent = path.dirname(candidate);
  const currentParentIdentity = assertDirectoryIdentity(parent, `${field} parent`);
  const currentIdentity = kind === "file" ? lstatIfExists(candidate) : assertDirectoryIdentity(candidate, field);
  if (
    currentIdentity === null ||
    !sameFilesystemIdentity(snapshot.parentIdentity, currentParentIdentity) ||
    !sameStableFileIdentity(snapshot.identity, currentIdentity)
  ) {
    throw new Error(`${field} identity changed`);
  }
  return candidate;
}

function executableCandidateNames(command, pathExtensions) {
  if (process.platform !== "win32" || path.extname(command)) {
    return [command];
  }
  return portableWindowsExecutableCandidateNames(command, pathExtensions);
}

export function portableWindowsExecutableExtensions(pathExtensions) {
  return String(pathExtensions ?? ".COM;.EXE;.BAT;.CMD")
    .split(";")
    .filter((extension) => /^\.[A-Za-z0-9]+$/u.test(extension));
}

export function portableWindowsExecutableCandidateNames(command, pathExtensions) {
  return portableWindowsExecutableExtensions(pathExtensions)
    .map((extension) => `${command}${extension}`)
    .filter((candidate) => Buffer.byteLength(candidate, "utf8") <= MAX_PORTABLE_COMPONENT_UTF8_BYTES);
}

function assertExecutablePermissions(metadata, field) {
  if (process.platform !== "win32" && (metadata.mode & 0o111n) === 0n) {
    throw new Error(`${field} is not executable`);
  }
}

function assertNoExistingSymbolicLinkComponents(candidate, field) {
  const parsed = path.parse(candidate);
  const relative = candidate.slice(parsed.root.length);
  let cursor = parsed.root;
  for (const component of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, component);
    if (lstatIfExists(cursor)?.isSymbolicLink()) {
      throw new Error(`${field} must not contain symbolic-link components: ${cursor}`);
    }
  }
}

function lstatIfExists(candidate) {
  try {
    // Windows file indexes and some Unix inode values exceed JavaScript's
    // exact Number range. BigInt stats keep identity comparisons lossless.
    return lstatSync(candidate, { bigint: true });
  } catch (error) {
    if (error?.code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

function assertDirectoryIdentity(candidate, field) {
  assertNoExistingSymbolicLinkComponents(candidate, field);
  const metadata = lstatIfExists(candidate);
  if (!metadata?.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error(`${field} must be a regular non-link directory`);
  }
  return metadata;
}

function assertSameDirectoryIdentity(candidate, expectedIdentity, field) {
  const metadata = assertDirectoryIdentity(candidate, field);
  if (!sameFilesystemIdentity(expectedIdentity, metadata)) {
    throw new Error(`${field} identity changed`);
  }
  return metadata;
}

export function sameFilesystemIdentity(left, right) {
  return left.dev === right.dev && left.ino === right.ino;
}

export function fitPortablePathComponentWithSuffix(baseValue, suffixValue, field = "path component") {
  const base = String(baseValue);
  const suffix = String(suffixValue);
  if (CONTROL_CHARACTER_PATTERN.test(base) || CONTROL_CHARACTER_PATTERN.test(suffix)) {
    throw new Error(`${field} contains invalid Unicode or control characters`);
  }
  const availableBytes = MAX_PORTABLE_COMPONENT_UTF8_BYTES - Buffer.byteLength(suffix, "utf8");
  if (availableBytes <= 0) {
    throw new Error(`${field} suffix is too long`);
  }
  let fittedBase = "";
  let usedBytes = 0;
  for (const character of base) {
    const characterBytes = Buffer.byteLength(character, "utf8");
    if (usedBytes + characterBytes > availableBytes) {
      break;
    }
    fittedBase += character;
    usedBytes += characterBytes;
  }
  if (!fittedBase) {
    throw new Error(`${field} base is too long for its suffix`);
  }
  const candidate = `${fittedBase}${suffix}`;
  assertPortablePathComponent(candidate, field);
  return candidate;
}

export function fitPortablePathComponentPrefix(
  prefixValue,
  { reservedSuffixBytes = 16, field = "path component prefix" } = {},
) {
  if (!Number.isInteger(reservedSuffixBytes) || reservedSuffixBytes <= 0) {
    throw new Error("reserved suffix bytes must be a positive integer");
  }
  const placeholder = "x".repeat(reservedSuffixBytes);
  const candidate = fitPortablePathComponentWithSuffix(prefixValue, placeholder, field);
  return candidate.slice(0, -reservedSuffixBytes);
}

export function portableTemporaryPathPrefix(
  prefixPath,
  { reservedSuffixBytes = 16, field = "temporary path prefix" } = {},
) {
  const raw = String(prefixPath);
  if (!raw || raw !== raw.trim() || CONTROL_CHARACTER_PATTERN.test(raw) || !path.isAbsolute(raw)) {
    throw new Error(`${field} must be an exact absolute path`);
  }
  const parent = resolveExactAbsolutePath(path.dirname(raw), `${field} parent`);
  const prefix = fitPortablePathComponentPrefix(path.basename(raw), {
    reservedSuffixBytes,
    field,
  });
  return path.join(parent, prefix);
}

export function portableSiblingPath(targetPath, suffix, field = "private sibling path") {
  const target = resolveExactAbsolutePath(targetPath, `${field} target`);
  const name = fitPortablePathComponentWithSuffix(path.basename(target), suffix, field);
  return path.join(path.dirname(target), name);
}

function assertPortablePathComponent(component, field) {
  if (
    !component ||
    component === "." ||
    component === ".." ||
    component !== component.trim() ||
    CONTROL_CHARACTER_PATTERN.test(component) ||
    /[<>:"/\\|?*]/u.test(component) ||
    component.endsWith(".") ||
    Buffer.byteLength(component, "utf8") > MAX_PORTABLE_COMPONENT_UTF8_BYTES ||
    WINDOWS_RESERVED_NAMES.has(component.split(".", 1)[0].toUpperCase())
  ) {
    throw new Error(`${field} contains a non-portable path component`);
  }
}

function portableNameKey(value) {
  return value.normalize("NFC").toUpperCase().toLowerCase();
}

function isSameOrWithin(candidatePath, rootPath) {
  const candidate = portableAbsolutePathParts(candidatePath);
  const root = portableAbsolutePathParts(rootPath);
  return (
    candidate.root === root.root &&
    candidate.components.length >= root.components.length &&
    root.components.every((component, index) => candidate.components[index] === component)
  );
}

function samePath(left, right) {
  const leftParts = portableAbsolutePathParts(left);
  const rightParts = portableAbsolutePathParts(right);
  return (
    leftParts.root === rightParts.root &&
    leftParts.components.length === rightParts.components.length &&
    leftParts.components.every((component, index) => rightParts.components[index] === component)
  );
}

function portableAbsolutePathParts(value) {
  const absolute = path.resolve(value);
  const parsed = path.parse(absolute);
  return {
    root: portableNameKey(parsed.root.replaceAll("\\", "/")),
    components: absolute.slice(parsed.root.length).split(path.sep).filter(Boolean).map(portableNameKey),
  };
}
