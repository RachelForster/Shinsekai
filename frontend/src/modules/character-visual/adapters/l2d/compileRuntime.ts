import ts from "typescript";
import bridge from "../../../../../scripts/l2d-sdk-bridge.mjs?raw";

/** Compile only the pinned, host-validated SDK inputs. No eval, CDN or Node runtime. */
export async function compileRuntime(input: unknown, signal: AbortSignal): Promise<string> {
  signal.throwIfAborted();
  if (ts.version !== "5.9.3") throw new Error("SDK preparation requires TypeScript 5.9.3");
  const sources = (input as { sources?: Record<string, string> } | null)?.sources;
  if (!sources || typeof sources !== "object" || Object.keys(sources).length > 256) {
    throw new Error("Invalid SDK sources");
  }
  const files: Record<string, string> = { ...sources, "bridge.ts": bridge.replaceAll("\r\n", "\n") };
  const compiled = new Map<string, { code: string; dependencies: Record<string, string> }>();
  const queue = ["bridge.ts"];
  while (queue.length) {
    signal.throwIfAborted();
    const id = queue.shift()!;
    if (compiled.has(id)) continue;
    const source = files[id];
    if (typeof source !== "string" || source.length > 2 * 1024 * 1024) throw new Error(`Missing SDK source: ${id}`);
    const dependencies: Record<string, string> = {};
    for (const reference of ts.preProcessFile(source, true, true).importedFiles) {
      const specifier = reference.fileName;
      let target: string;
      if (specifier.startsWith("shinsekai-cubism/"))
        target = `Framework/src/${specifier.slice("shinsekai-cubism/".length)}`;
      else if (specifier.startsWith(".")) {
        const parts = id.split("/").slice(0, -1);
        for (const part of specifier.split("/")) {
          if (part === "..") parts.pop();
          else if (part !== ".") parts.push(part);
        }
        target = parts.join("/");
      } else throw new Error(`Unsupported SDK dependency: ${specifier}`);
      target = target.replace(/\.js$/, ".ts");
      if (!target.endsWith(".ts")) target += ".ts";
      if (!target.startsWith("Framework/src/") || !(target in sources)) {
        throw new Error(`Missing SDK dependency: ${target}`);
      }
      dependencies[specifier] = target;
      queue.push(target);
    }
    const result = ts.transpileModule(source.replaceAll("\r\n", "\n"), {
      fileName: id,
      reportDiagnostics: true,
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
        newLine: ts.NewLineKind.LineFeed,
      },
    });
    if (result.diagnostics?.some((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error)) {
      throw new Error(`Cannot compile SDK source: ${id}`);
    }
    compiled.set(id, { code: result.outputText, dependencies });
    // Release the UI thread between modules; dialog progress remains responsive.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
  const modules = [...compiled.keys()].sort().map((id) => {
    const { code, dependencies } = compiled.get(id)!;
    return `${JSON.stringify(id)}: [function(require,module,exports){\n${code}\n},${JSON.stringify(dependencies)}]`;
  });
  return `// User-installed Cubism 5-r.4; original license notices retained.\nconst modules={\n${modules.join(",\n")}\n};
const cache=Object.create(null);
function load(id){
 if(cache[id]) return cache[id].exports;
 const entry=modules[id]; if(!entry) throw new Error("Missing SDK module: "+id);
 const module={exports:{}}; cache[id]=module;
 entry[0](name=>load(entry[1][name]),module,module.exports); return module.exports;
}
const bridge=load("bridge.ts");
export const SDK_VERSION=bridge.SDK_VERSION;
export const initialize=bridge.initialize;
export const createModel=bridge.createModel;
export const createMatrix=bridge.createMatrix;
export const releaseContext=bridge.releaseContext;
`;
}
