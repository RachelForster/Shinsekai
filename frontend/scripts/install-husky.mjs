import { fileURLToPath } from "node:url";
import path from "node:path";

if (process.env.CI === "true" || process.env.NODE_ENV === "production") {
  process.exit(0);
}

const frontendDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
process.chdir(path.resolve(frontendDirectory, ".."));

const husky = (await import("husky")).default;
const message = husky();

if (message) {
  console.log(message);
}
