import { defineConfig } from "@playwright/test";

import baseConfig from "./playwright.config";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174";
const localNoProxy = "127.0.0.1,localhost,::1";

function appendLocalNoProxy(value: string | undefined) {
  if (!value) {
    return localNoProxy;
  }
  const entries = new Set(
    value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
  );
  localNoProxy.split(",").forEach((entry) => entries.add(entry));
  return Array.from(entries).join(",");
}

process.env.NO_PROXY = appendLocalNoProxy(process.env.NO_PROXY);
process.env.no_proxy = appendLocalNoProxy(process.env.no_proxy);

const webServerEnv: Record<string, string> = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
);

const managedServerConfig = process.env.PLAYWRIGHT_BASE_URL
  ? {}
  : {
      webServer: {
        command: "pnpm dev --host 127.0.0.1 --port 5174",
        env: {
          ...webServerEnv,
          ALL_PROXY: "",
          HTTP_PROXY: "",
          HTTPS_PROXY: "",
          NO_PROXY: process.env.NO_PROXY,
          all_proxy: "",
          http_proxy: "",
          https_proxy: "",
          no_proxy: process.env.no_proxy,
        },
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        url: baseURL,
      },
    };

export default defineConfig({
  ...baseConfig,
  ...managedServerConfig,
});
