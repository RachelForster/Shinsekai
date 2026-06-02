import { describe, expect, it } from "vitest";

import type { PluginManifest, PluginUIPage } from "../entities/plugin/types";
import {
  catalogInstallSource,
  fallbackPluginUiPages,
  githubUrl,
  pluginActionId,
  pluginConfigGroupsToFormGroups,
  pluginConfigInitialValues,
  pluginFieldTypeToFormType,
  pluginHasManifestEntry,
  pluginInstallSource,
  pluginSettingsPages,
  pluginToolsTabs,
  pluginUiPageKey,
} from "../features/plugin-manager/pluginUtils";

const plugin: PluginManifest = {
  author: "Tester",
  description: "Demo plugin",
  directory: "plugins/demo",
  enabled: true,
  entry: "plugins.demo:Plugin",
  id: "demo",
  loaded: true,
  permissions: ["chat:read"],
  settingsPages: ["General", "Advanced"],
  slots: ["chat-output"],
  title: "Demo",
  toolsTabs: ["Tools"],
  version: "1.2.3",
};

describe("plugin manager utilities", () => {
  it("uses stable source and action identifiers", () => {
    expect(
      catalogInstallSource({
        author: "Tester",
        description: "",
        downloaded: false,
        entry: "plugins.demo:Plugin",
        installed: false,
        name: "Demo",
        repo: "owner/demo",
      }),
    ).toBe("owner/demo");
    expect(githubUrl("owner/demo")).toBe("https://github.com/owner/demo");
    expect(githubUrl("https://github.com/owner/demo.git")).toBe("https://github.com/owner/demo");
    expect(githubUrl("github.com/owner/demo/tree/main")).toBe("https://github.com/owner/demo/tree/main");
    expect(githubUrl("https://github.com/owner/demo/releases/tag/v1.0.0")).toBe(
      "https://github.com/owner/demo/releases/tag/v1.0.0",
    );
    expect(githubUrl("")).toBe("");
    expect(pluginActionId(plugin)).toBe("plugins.demo:Plugin");
    expect(pluginActionId({ ...plugin, entry: "" })).toBe("demo");
    expect(pluginHasManifestEntry(plugin)).toBe(true);
    expect(pluginHasManifestEntry({ ...plugin, entry: "  " })).toBe(false);
    expect(pluginInstallSource("owner/demo")).toBe("owner/demo");
    expect(pluginInstallSource({ source: "plugins.demo:Plugin" })).toBe("plugins.demo:Plugin");
  });

  it("builds fallback UI pages from legacy plugin metadata", () => {
    expect(pluginSettingsPages(null)).toEqual([]);
    expect(pluginSettingsPages(plugin)).toEqual(["General", "Advanced"]);
    expect(pluginToolsTabs(null)).toEqual([]);
    expect(pluginToolsTabs(plugin)).toEqual(["Tools"]);

    const pages = fallbackPluginUiPages(plugin);
    expect(pages.map((page) => [page.kind, page.id, page.order, page.title])).toEqual([
      ["settings", "settings-0", 0, "General"],
      ["settings", "settings-1", 1, "Advanced"],
      ["tools", "tools-0", 2, "Tools"],
    ]);
    expect(pages.every((page) => page.pluginId === "demo" && page.pluginVersion === "1.2.3")).toBe(true);
    expect(fallbackPluginUiPages(null)).toEqual([]);
  });

  it("maps plugin config schema into reusable form schema", () => {
    const formGroups = pluginConfigGroupsToFormGroups([
      {
        description: "Runtime options",
        fields: [
          { defaultValue: true, key: "enabled", label: "Enabled", required: true, type: "boolean" },
          { key: "mode", label: "Mode", options: [{ label: "Fast", value: "fast" }], type: "select" },
          { key: "retries", label: "Retries", max: 5, min: 0, step: 1, type: "number" },
        ],
        id: "runtime",
        title: "Runtime",
      },
    ]);

    expect(pluginFieldTypeToFormType("boolean")).toBe("checkbox");
    expect(pluginFieldTypeToFormType("text")).toBe("text");
    expect(formGroups).toHaveLength(1);
    expect(formGroups[0]).toMatchObject({
      columns: 1,
      description: "Runtime options",
      id: "runtime",
      title: "Runtime",
    });
    expect(formGroups[0].fields.map((field) => [field.name, field.type, field.defaultValue])).toEqual([
      ["enabled", "checkbox", true],
      ["mode", "select", undefined],
      ["retries", "number", undefined],
    ]);
    expect(formGroups[0].fields[1].options).toEqual([{ label: "Fast", value: "fast" }]);
    expect(formGroups[0].fields[2]).toMatchObject({ max: 5, min: 0, step: 1 });
  });

  it("hydrates config drafts from saved values before defaults", () => {
    const page: PluginUIPage = {
      id: "settings",
      kind: "settings",
      order: 0,
      pluginId: "demo",
      pluginVersion: "1.2.3",
      schema: [
        {
          fields: [
            { defaultValue: "safe", key: "mode", label: "Mode", type: "text" },
            { defaultValue: 3, key: "retries", label: "Retries", type: "number" },
            { defaultValue: false, key: "enabled", label: "Enabled", type: "boolean" },
          ],
          id: "runtime",
          title: "Runtime",
        },
      ],
      title: "Settings",
      values: {
        enabled: true,
        mode: "fast",
      },
    };

    expect(pluginUiPageKey(page)).toBe("settings:settings");
    expect(pluginConfigInitialValues(page)).toEqual({
      enabled: true,
      mode: "fast",
      retries: 3,
    });
    expect(pluginConfigInitialValues({ ...page, schema: undefined, values: { mode: "fast" } })).toEqual({});
  });
});
