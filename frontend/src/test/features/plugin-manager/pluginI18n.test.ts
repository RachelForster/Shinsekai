import { describe, expect, it } from "vitest";

import {
  fallbackPluginUiPages,
  localizePluginUiPage,
  pluginActionId,
  pluginConfigGroupsToFormGroups,
  pluginConfigInitialValues,
  pluginHasManifestEntry,
  pluginInstallSource,
  pluginSettingsPages,
  pluginToolsTabs,
  pluginUiPageKey,
} from "../../../features/plugin-manager/pluginUtils";
import type { PluginManifest, PluginUIPage } from "../../../shared/platform/types";

function makePage(): PluginUIPage {
  return {
    description: "Default description",
    i18n: {
      en: {
        description: "English description",
        groups: {
          main: {
            description: "English group description",
            fields: {
              enabled: {
                description: "English enabled description",
                label: "English enabled",
                options: { yes: "English yes" },
                placeholder: "English placeholder",
              },
            },
            title: "English group",
          },
        },
        restartHint: "English restart hint",
        title: "English page",
      },
      zh_CN: {
        title: "ZH page",
      },
    },
    id: "demo",
    kind: "settings",
    order: 1,
    pluginId: "demo.plugin",
    pluginVersion: "1.0.0",
    restartHint: "Restart required",
    schema: [
      {
        description: "Default group description",
        fields: [
          {
            defaultValue: false,
            description: "Default enabled description",
            key: "enabled",
            label: "Enabled",
            options: [{ label: "Yes", value: "yes" }],
            placeholder: "Choose",
            type: "boolean",
          },
          {
            defaultValue: { retries: 2 },
            key: "extra",
            label: "Extra JSON",
            span: "full",
            type: "json",
          },
        ],
        id: "main",
        title: "Main",
      },
    ],
    title: "Demo page",
    values: { enabled: true },
  };
}

describe("plugin config i18n", () => {
  it("overrides page, group, field, and option labels for the active language", () => {
    const localized = localizePluginUiPage(makePage(), "en");
    const groups = pluginConfigGroupsToFormGroups(localized.schema ?? []);

    expect(localized.title).toBe("English page");
    expect(localized.description).toBe("English description");
    expect(localized.restartHint).toBe("English restart hint");
    expect(groups[0]).toMatchObject({
      description: "English group description",
      title: "English group",
    });
    expect(groups[0]?.fields[0]).toMatchObject({
      description: "English enabled description",
      label: "English enabled",
      options: [{ label: "English yes", value: "yes" }],
      placeholder: "English placeholder",
    });
  });

  it("falls back to English strings when the requested language is missing", () => {
    const localized = localizePluginUiPage(makePage(), "ja");

    expect(localized.title).toBe("English page");
    expect(localized.schema?.[0]?.fields[0]?.label).toBe("English enabled");
  });

  it("maps frontend configuration fields without losing JSON and boolean semantics", () => {
    const groups = pluginConfigGroupsToFormGroups(makePage().schema ?? []);

    expect(groups[0]?.fields[0]).toMatchObject({ name: "enabled", type: "checkbox" });
    expect(groups[0]?.fields[1]).toMatchObject({ name: "extra", span: "full", type: "json" });
  });

  it("uses saved values before field defaults when building the config draft", () => {
    const draft = pluginConfigInitialValues(makePage());

    expect(draft).toEqual({
      enabled: true,
      extra: { retries: 2 },
    });
  });
});

describe("plugin manager utilities", () => {
  const plugin: PluginManifest = {
    author: "Tester",
    description: "Utility plugin",
    directory: "plugins/utility",
    enabled: true,
    entry: "plugins.utility:Plugin",
    id: "utility",
    loaded: true,
    permissions: ["settings"],
    settingsPages: ["Settings", "Advanced"],
    slots: ["settings-extension"],
    title: "Utility",
    toolsTabs: ["Inspector"],
    version: "1.0.0",
  };

  it("uses manifest entry as the action id and detects missing entries", () => {
    expect(pluginActionId(plugin)).toBe("plugins.utility:Plugin");
    expect(pluginActionId({ ...plugin, entry: "", id: "fallback" })).toBe("fallback");
    expect(pluginHasManifestEntry(plugin)).toBe(true);
    expect(pluginHasManifestEntry({ ...plugin, entry: "   " })).toBe(false);
  });

  it("normalizes install sources and plugin page lists", () => {
    expect(pluginInstallSource("owner/repo")).toBe("owner/repo");
    expect(pluginInstallSource({ source: "plugins.demo:Plugin", tagName: "v1.0.0" })).toBe("plugins.demo:Plugin");
    expect(pluginSettingsPages(plugin)).toEqual(["Settings", "Advanced"]);
    expect(pluginToolsTabs(plugin)).toEqual(["Inspector"]);
    expect(pluginSettingsPages(null)).toEqual([]);
    expect(pluginToolsTabs(null)).toEqual([]);
  });

  it("creates stable fallback UI page keys for settings and tools pages", () => {
    const pages = fallbackPluginUiPages(plugin);

    expect(pages.map(pluginUiPageKey)).toEqual(["settings:settings-0", "settings:settings-1", "tools:tools-0"]);
    expect(pages.map((page) => [page.title, page.order, page.pluginId, page.pluginVersion])).toEqual([
      ["Settings", 0, "utility", "1.0.0"],
      ["Advanced", 1, "utility", "1.0.0"],
      ["Inspector", 2, "utility", "1.0.0"],
    ]);
    expect(fallbackPluginUiPages(null)).toEqual([]);
  });
});
