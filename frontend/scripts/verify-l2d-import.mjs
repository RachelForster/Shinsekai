// Explicit local verification only. Requires a licensed SDK ZIP, never downloads one.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const project = path.dirname(frontend);
const argument = (name) => process.argv[process.argv.indexOf(name) + 1];
if (!process.argv.includes("--sdk-zip") || !process.argv.includes("--python")) {
  throw new Error(
    "Usage: node scripts/verify-l2d-import.mjs --sdk-zip <licensed 5-r.4 ZIP> --python <shinsekai Python> [--dist <build directory>]",
  );
}
const zip = path.resolve(argument("--sdk-zip"));
const python = argument("--python");
const dist = process.argv.includes("--dist") ? path.resolve(argument("--dist")) : path.join(frontend, "dist");
const compiler = (await readdir(path.join(dist, "web-assets"))).find((file) => /^compileRuntime-.*\.js$/.test(file));
assert.ok(compiler, "Build the frontend first");
const runPython = (source, ...args) =>
  JSON.parse(
    execFileSync(python, ["-c", source, ...args], {
      cwd: project,
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
    }),
  );
const prepared = runPython(
  "import json,sys; from pathlib import Path; from core.media.avatar.l2d_sdk import Live2DRuntimeInstaller; print(json.dumps(Live2DRuntimeInstaller().prepare(Path(sys.argv[1]))))",
  zip,
);
const temporaryRoot = path.join(project, ".tmp");
await mkdir(temporaryRoot, { recursive: true });
const evidence = await mkdtemp(path.join(temporaryRoot, "l2d-import-verify-"));
let installedFiles = {};
const requests = [];
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    requests.push(url.pathname);
    if (url.pathname === "/") {
      response.setHeader("Content-Type", "text/html");
      response.end("<!doctype html><title>Local SDK import verification</title>");
      return;
    }
    const selected =
      url.pathname === "/model.moc3"
        ? path.join(frontend, "public/live2d/models/Haru/Haru.moc3")
        : ["/live2d/live2dcubismcore.min.js", "/live2d/cubism-sdk.js"].includes(url.pathname)
          ? path.join(frontend, "public", url.pathname.slice(1))
          : url.pathname.startsWith("/runtime/")
            ? installedFiles[url.pathname.slice(9)]
            : undefined;
    const file = selected || path.resolve(dist, `.${decodeURIComponent(url.pathname)}`);
    assert.ok(selected || file.startsWith(dist + path.sep));
    response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : "application/octet-stream");
    response.end(await readFile(file));
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base);
  // SDK preparation is an explicit operation, not part of page initialization.
  assert.equal(
    requests.some((url) => url.includes("l2d-compiler")),
    false,
  );
  // Reproduce the review path: this page has already initialized the developer
  // fallback before the host installs a runtime. A preview remount is not enough
  // to replace its global Core; installation must navigate to a fresh page.
  await page.evaluate(async () => {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/live2d/live2dcubismcore.min.js";
      script.onload = resolve;
      script.onerror = reject;
      document.head.append(script);
    });
    const sdk = await import("/live2d/cubism-sdk.js");
    sdk.initialize();
    globalThis.fallbackSdk = sdk;
  });
  const compiled = await page.evaluate(
    async ({ prepared, compiler }) => {
      const module = await import(`/web-assets/${compiler}`);
      const signal = new AbortController().signal;
      const first = await module.compileRuntime(prepared, signal);
      const second = await module.compileRuntime(prepared, signal);
      if (first !== second) throw new Error("Non-deterministic SDK compiler");
      return first;
    },
    { prepared, compiler },
  );
  assert.equal(
    createHash("sha256").update(compiled).digest("hex"),
    "1eed52ae04123efa8b482f435807e9f566f00c9459ff0259c002c4f33628a565",
  );
  assert.ok(requests.some((url) => url.includes("l2d-compiler")));
  const compiledPath = path.join(evidence, "cubism-sdk.js");
  await writeFile(compiledPath, compiled);
  const result = runPython(
    `import json,sys
from pathlib import Path
from core.media.avatar.registry import configure_builtin_formats
from application.media.avatar_runtime import AvatarRuntimeService
configure_builtin_formats()
service=AvatarRuntimeService(Path(sys.argv[1]), file_access_roots=[Path(sys.argv[2]).parent])
status=service.install('l2d', {'source_path':sys.argv[2], 'accepted_license':True, 'compiled':Path(sys.argv[3]).read_text(encoding='utf-8')})
print(json.dumps({'status':status,'files':{name:str(service.file('l2d',name)) for name in ('cubism-sdk.js','live2dcubismcore.min.js')}}))`,
    path.join(evidence, "project"),
    zip,
    compiledPath,
  );
  assert.equal(result.status.installed, true);
  installedFiles = result.files;
  await page.reload();
  assert.equal(await page.evaluate(() => typeof globalThis.Live2DCubismCore), "undefined");
  assert.equal(await page.evaluate(() => typeof globalThis.fallbackSdk), "undefined");
  const afterReload = requests.length;
  const parameters = await page.evaluate(async () => {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/runtime/live2dcubismcore.min.js";
      script.onload = resolve;
      script.onerror = reject;
      document.head.append(script);
    });
    const sdk = await import("/runtime/cubism-sdk.js");
    sdk.initialize();
    const model = sdk.createModel();
    const moc = await fetch("/model.moc3").then((response) => {
      if (!response.ok) throw new Error("Prepare the authorized local Haru sample to verify rendering inputs");
      return response.arrayBuffer();
    });
    model.loadModel(moc, true);
    const count = model.getModel().getParameterCount();
    model.release();
    return count;
  });
  assert.ok(parameters > 0);
  assert.ok(requests.slice(afterReload).includes("/runtime/live2dcubismcore.min.js"));
  assert.ok(requests.slice(afterReload).includes("/runtime/cubism-sdk.js"));
  assert.equal(
    requests.slice(afterReload).some((url) => url.startsWith("/live2d/")),
    false,
  );
  assert.deepEqual(errors, []);
  console.info(
    `Browser compilation, durable installation, fallback-to-installed Core/SDK after reload and Haru (${parameters} parameters): passed. Evidence: ${evidence}`,
  );
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
