import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

// Validate copied Python sources without executing a possibly cross-compiled runtime.
export async function verifyLlmRuntimeSources(sourceRoot, runtimeRoot) {
  for (const directory of ["ai/llm", "sdk", "application/chat"]) {
    const files = await pythonFiles(path.join(sourceRoot, directory));
    for (const sourceFile of files) {
      const relativePath = path.relative(sourceRoot, sourceFile);
      const displayPath = relativePath.split(path.sep).join("/");
      const source = await readFile(sourceFile);
      let packaged;
      try {
        packaged = await readFile(path.join(runtimeRoot, relativePath));
      } catch (error) {
        if (error.code !== "ENOENT") {
          throw error;
        }
        throw new Error(
          `Incomplete chat runtime at ${runtimeRoot}: missing ${displayPath}. Rebuild application resources from the same checkout.`,
        );
      }
      if (!source.equals(packaged)) {
        throw new Error(
          `Stale chat runtime at ${runtimeRoot}: ${displayPath} differs from the source checkout. Rebuild application resources together to keep SDK, LLM and chat services compatible.`,
        );
      }
    }
  }
}

async function pythonFiles(directory) {
  const files = [];
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory() && entry.name !== "__pycache__") {
      files.push(...(await pythonFiles(entryPath)));
    } else if (entry.isFile() && entry.name.endsWith(".py")) {
      files.push(entryPath);
    }
  }
  return files;
}
