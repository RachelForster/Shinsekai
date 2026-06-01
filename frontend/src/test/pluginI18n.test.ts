import { describe, expect, it } from "vitest";

import {
  localizePluginUiPage,
  pluginConfigGroupsToFormGroups,
  pluginConfigInitialValues,
} from "../features/plugin-manager/pluginUtils";
import type { PluginUIPage } from "../shared/platform/types";

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
