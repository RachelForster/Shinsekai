import { copyFile, mkdir, access, readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const args = process.argv.slice(2);
const sdkIndex = args.indexOf("--sdk-dir");
if (!args.includes("--accept-sdk-license") || sdkIndex < 0 || !args[sdkIndex + 1]) {
  throw new Error(
    "Usage: pnpm prepare:l2d --sdk-dir <CubismSdkForWeb-5-r.4> --accept-sdk-license. Read the SDK's Framework/Core licenses first. No SDK is downloaded automatically.",
  );
}
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sdk = resolve(args[sdkIndex + 1]);
const resources = resolve(frontend, "public/live2d");
const core = resolve(sdk, "Core/live2dcubismcore.min.js");
const version = (await readFile(resolve(sdk, "CHANGELOG.md"), "utf8")).match(/^## \[([^\]]+)\]/m)?.[1];
if (version !== "5-r.4") throw new Error("Only the pinned Cubism SDK 5-r.4 is supported by this runtime bridge.");
await access(core);
await access(resolve(sdk, "Framework/src/rendering/cubismshader_webgl.ts"));
await access(resolve(sdk, "Framework/LICENSE.md"));
await access(resolve(sdk, "Core/LICENSE.md"));
await mkdir(resources, { recursive: true });
await build({
  configFile: false,
  root: frontend,
  publicDir: false,
  resolve: { alias: { "shinsekai-cubism": resolve(sdk, "Framework/src") } },
  build: {
    outDir: resources,
    emptyOutDir: false,
    lib: { entry: resolve(frontend, "scripts/l2d-sdk-bridge.mjs"), formats: ["es"], fileName: () => "cubism-sdk.js" },
    minify: false,
  },
});
await copyFile(core, resolve(resources, "live2dcubismcore.min.js"));
await copyFile(resolve(sdk, "Framework/LICENSE.md"), resolve(resources, "cubism-framework-LICENSE.md"));
await copyFile(resolve(sdk, "Core/LICENSE.md"), resolve(resources, "cubism-core-LICENSE.md"));
console.log(
  "Local SDK prepared. Generated SDK files stay ignored; no models are copied. Distribution requires a separate license review.",
);
