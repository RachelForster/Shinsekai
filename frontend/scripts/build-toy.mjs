import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const distToyDir = path.join(frontendDir, "dist-toy");

function runNodeScript(binRelPath, args) {
  const fullBinPath = path.join(frontendDir, binRelPath);
  if (!fs.existsSync(fullBinPath)) {
    throw new Error(`Missing node tool binary: ${fullBinPath}`);
  }
  execFileSync(process.execPath, [fullBinPath, ...args], {
    cwd: frontendDir,
    stdio: "inherit",
  });
}

console.log("[build:toy] Running TypeScript typecheck...");
runNodeScript("node_modules/typescript/bin/tsc", ["-b", "--pretty", "false"]);

console.log("[build:toy] Building Bilibili Toy static package into dist-toy/...");
runNodeScript("node_modules/vite/bin/vite.js", ["build", "--config", "vite.toy.config.ts"]);

const indexHtmlPath = path.join(distToyDir, "index.html");
if (!fs.existsSync(indexHtmlPath)) {
  throw new Error(`Expected dist-toy/index.html to exist at ${indexHtmlPath}`);
}
const indexSizeBytes = fs.statSync(indexHtmlPath).size;
console.log(`[build:toy] dist-toy/index.html size: ${(indexSizeBytes / 1024).toFixed(2)} KB`);
if (indexSizeBytes >= 1024 * 1024) {
  throw new Error(`dist-toy/index.html exceeds 1MB limit (${indexSizeBytes} bytes)`);
}

const candidateDoctorPaths = [
  path.join(os.homedir(), ".gemini", "config", "skills", "toy", "scripts", "toy_doctor.py"),
  path.join(os.homedir(), ".agents", "skills", "toy", "scripts", "toy_doctor.py"),
];
const doctorScript = candidateDoctorPaths.find((candidate) => fs.existsSync(candidate));

if (doctorScript) {
  console.log(`[build:toy] Running toy_doctor.py preflight check (${doctorScript})...`);
  const pythonExe = process.env.PYTHON || "python";
  const output = execFileSync(pythonExe, [doctorScript, distToyDir, "--slug", "shinsekai-toy", "--json"], {
    cwd: frontendDir,
    encoding: "utf8",
  });
  console.log(output);
  const report = JSON.parse(output);
  if (!report.ok) {
    throw new Error("[build:toy] toy_doctor.py reported errors.");
  }
} else {
  console.log("[build:toy] toy_doctor.py not found in standard skill directories; skipping preflight script.");
}

console.log("[build:toy] Bilibili Toy package ready in frontend/dist-toy/");
