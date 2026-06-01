import { describe, expect, it } from "vitest";

import { localizePluginUiPage, pluginConfigGroupsToFormGroups } from "../features/plugin-manager/pluginUtils";
import type { PluginUIPage } from "../shared/platform/types";

describe("plugin config i18n", () => {
  const page: PluginUIPage = {
    description: "Default description",
    i18n: {
      zh_CN: {
        description: "默认说明",
        groups: {
          main: {
            fields: {
              enabled: {
                description: "是否启用插件",
                label: "启用",
                options: { yes: "是" },
                placeholder: "请选择",
              },
            },
            title: "主要",
          },
        },
        restartHint: "需要重启",
        title: "演示页面",
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
        fields: [
          {
            key: "enabled",
            label: "Enabled",
            options: [{ label: "Yes", value: "yes" }],
            placeholder: "Choose",
            type: "select",
          },
        ],
        id: "main",
        title: "Main",
      },
    ],
    title: "Demo page",
    values: { enabled: "yes" },
  };

  it("overrides page, group, field, and option labels for the active language", () => {
    const localized = localizePluginUiPage(page, "zh_CN");
    const groups = pluginConfigGroupsToFormGroups(localized.schema ?? []);

    expect(localized.title).toBe("演示页面");
    expect(localized.description).toBe("默认说明");
    expect(localized.restartHint).toBe("需要重启");
    expect(groups[0]?.title).toBe("主要");
    expect(groups[0]?.fields[0]).toMatchObject({
      description: "是否启用插件",
      label: "启用",
      options: [{ label: "是", value: "yes" }],
      placeholder: "请选择",
    });
  });

  it("falls back to default strings when a language is missing", () => {
    const localized = localizePluginUiPage(page, "ja");

    expect(localized.title).toBe("演示页面");
    expect(localized.schema?.[0]?.fields[0]?.label).toBe("启用");
  });
});
