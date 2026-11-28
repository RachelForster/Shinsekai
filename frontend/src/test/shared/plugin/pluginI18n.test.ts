import { describe, expect, it } from "vitest";

import {
  localizePluginSection,
  localizePluginSidebarPage,
  localizePluginSlotContribution,
  localizePluginUiPage,
  resolveLocalizedEntry,
  resolveLocalizedText,
} from "../../../shared/plugin/pluginI18n";
import type {
  PluginSectionContribution,
  PluginSidebarPageContribution,
  PluginSlotContribution,
  PluginUIPage,
} from "../../../shared/platform/types";

describe("pluginI18n helpers", () => {
  it("resolves exact, short-prefix, en, zh_CN, and first fallback entries", () => {
    const entries = { en: { v: "english" }, zh: { v: "chinese" } };
    expect(resolveLocalizedEntry(entries, "zh_CN")).toEqual({ v: "chinese" });
    expect(resolveLocalizedEntry(entries, "ja")).toEqual({ v: "english" });
    expect(resolveLocalizedEntry({ ja: { v: "japanese" } }, "en")).toEqual({ v: "japanese" });
    expect(resolveLocalizedText({ en: "Hello", zh_CN: "你好" }, "zh_CN", "Fallback")).toBe("你好");
    expect(resolveLocalizedText(undefined, "en", "Fallback")).toBe("Fallback");
  });

  it("localizes slot contributions, sidebar pages, sections, and UI pages", () => {
    const slotItem: PluginSlotContribution = {
      actionLabel: "Open",
      actionType: "callback",
      actionable: true,
      description: "Default description",
      i18n: {
        zh_CN: { label: "运行动作", title: "动作标题", tooltip: "快捷提示" },
      },
      icon: "wand",
      id: "quick",
      order: 10,
      pageId: "",
      pluginId: "demo",
      pluginVersion: "1.0.0",
      presentation: "button",
      slot: "system-header-actions",
      title: "Action",
      variant: "ghost",
    };
    expect(localizePluginSlotContribution(slotItem, "zh_CN")).toMatchObject({
      actionLabel: "运行动作",
      description: "快捷提示",
      title: "动作标题",
    });

    const sidebarItem: PluginSidebarPageContribution = {
      description: "Desc",
      frontendUrl: "/api/plugins/demo/frontend/board/",
      i18n: { ja: { description: "ボード説明", navLabel: "ゲーム盤", title: "人狼ゲーム" } },
      navIcon: "gamepad",
      navLabel: "Board",
      order: 10,
      pageId: "board",
      pluginId: "demo",
      pluginVersion: "1.0.0",
      title: "Game Board",
    };
    expect(localizePluginSidebarPage(sidebarItem, "ja")).toMatchObject({
      description: "ボード説明",
      navLabel: "ゲーム盤",
      title: "人狼ゲーム",
    });

    const sectionItem: PluginSectionContribution = {
      actions: [
        { confirm: "Sure?", description: "Reset all", id: "reset", label: "Reset", order: 1, variant: "ghost" },
      ],
      canSave: true,
      description: "Base desc",
      i18n: {
        zh_CN: {
          actions: { reset: { confirm: "确认重置？", label: "重置" } },
          fields: { mode: { label: "模式", options: { fast: "快速" } } },
          navLabel: "插件区",
          title: "插件区块",
        },
      },
      id: "extra",
      navLabel: "Extra",
      order: 10,
      page: "template",
      pluginId: "demo",
      pluginVersion: "1.0.0",
      renderer: "schema",
      schema: [
        {
          fields: [
            {
              key: "mode",
              label: "Mode",
              options: [{ label: "Fast", value: "fast" }],
              type: "select",
            },
          ],
          id: "main",
          title: "Main",
        },
      ],
      slot: "sidebar",
      title: "Extra Section",
    };
    const localizedSection = localizePluginSection(sectionItem, "zh_CN");
    expect(localizedSection.title).toBe("插件区块");
    expect(localizedSection.navLabel).toBe("插件区");
    expect(localizedSection.schema?.[0]?.fields[0]?.label).toBe("模式");
    expect(localizedSection.schema?.[0]?.fields[0]?.options?.[0]?.label).toBe("快速");
    expect(localizedSection.actions?.[0]).toMatchObject({ confirm: "确认重置？", label: "重置" });

    const page: PluginUIPage = {
      i18n: { en: { navLabel: "Sidebar Label", restartHint: "Restart now", title: "EN Page" } },
      id: "page-1",
      kind: "settings",
      navLabel: "Old",
      order: 1,
      pluginId: "demo",
      pluginVersion: "1.0.0",
      title: "Page 1",
    };
    expect(localizePluginUiPage(page, "en")).toMatchObject({
      navLabel: "Sidebar Label",
      restartHint: "Restart now",
      title: "EN Page",
    });
  });
});
