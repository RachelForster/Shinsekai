import { describe, expect, it } from "vitest";

import { translateMessage } from "../../../shared/i18n";
import { frontendMessages } from "../../../shared/i18n/messages";
import { enMessageSlices } from "../../../shared/i18n/messages/en";
import { jaMessageSlices } from "../../../shared/i18n/messages/ja";
import { zhCNMessageSlices } from "../../../shared/i18n/messages/zh_CN";

function extractPlaceholders(template: string): string[] {
  return [...new Set([...template.matchAll(/\{(\w+)\}/g)].map((match) => match[1]))].sort();
}

describe("i18n domain slices", () => {
  it("keeps identical domain names and disjoint keys across all locales", () => {
    const domainNames = Object.keys(zhCNMessageSlices).sort();
    expect(Object.keys(enMessageSlices).sort()).toEqual(domainNames);
    expect(Object.keys(jaMessageSlices).sort()).toEqual(domainNames);

    const seenZhKeys = new Set<string>();
    let sliceKeyCount = 0;

    for (const domain of domainNames as Array<keyof typeof zhCNMessageSlices>) {
      const zhKeys = Object.keys(zhCNMessageSlices[domain]).sort();
      const enKeys = Object.keys(enMessageSlices[domain]).sort();
      const jaKeys = Object.keys(jaMessageSlices[domain]).sort();

      expect(zhKeys.length, `${domain} should not be empty`).toBeGreaterThan(0);
      expect(enKeys, `${domain} en keys`).toEqual(zhKeys);
      expect(jaKeys, `${domain} ja keys`).toEqual(zhKeys);

      for (const key of zhKeys) {
        expect(seenZhKeys.has(key), `duplicate i18n key across slices: ${key}`).toBe(false);
        seenZhKeys.add(key);
        sliceKeyCount += 1;
      }
    }

    expect(Object.keys(frontendMessages.zh_CN)).toHaveLength(sliceKeyCount);
    expect(Object.keys(frontendMessages.en).sort()).toEqual(Object.keys(frontendMessages.zh_CN).sort());
    expect(Object.keys(frontendMessages.ja).sort()).toEqual(Object.keys(frontendMessages.zh_CN).sort());
  });

  it("preserves interpolation placeholders across zh_CN, en, and ja", () => {
    const mismatches: string[] = [];
    for (const key of Object.keys(frontendMessages.zh_CN) as Array<keyof typeof frontendMessages.zh_CN>) {
      const zhPlaceholders = extractPlaceholders(frontendMessages.zh_CN[key]);
      const enPlaceholders = extractPlaceholders(frontendMessages.en[key]);
      const jaPlaceholders = extractPlaceholders(frontendMessages.ja[key]);
      if (
        zhPlaceholders.join(",") !== enPlaceholders.join(",") ||
        zhPlaceholders.join(",") !== jaPlaceholders.join(",")
      ) {
        mismatches.push(
          `${key}: zh=[${zhPlaceholders.join(",")}] en=[${enPlaceholders.join(",")}] ja=[${jaPlaceholders.join(",")}]`,
        );
      }
    }
    expect(mismatches).toEqual([]);
  });
});

describe("translateMessage", () => {
  it("returns localized messages for supported languages", () => {
    expect(translateMessage("zh_CN", "nav.plugins")).toBe("插件管理");
    expect(translateMessage("en", "nav.plugins")).toBe("Plugins");
    expect(translateMessage("ja", "nav.plugins")).toBe("プラグイン");
  });

  it("interpolates named values", () => {
    expect(translateMessage("zh_CN", "plugin.installed.count", { count: 3 })).toBe("3 个插件");
    expect(translateMessage("en", "plugin.installed.count", { count: 3 })).toBe("3 plugins");
  });

  it("covers schema settings page copy", () => {
    expect(translateMessage("zh_CN", "api.title")).toBe("AI 服务设置");
    expect(translateMessage("en", "system.toast.saved")).toBe("System settings saved");
    expect(translateMessage("ja", "form.jsonInvalid")).toContain("JSON");
  });

  it("covers T2I setup copy without falling back to raw keys", () => {
    expect(translateMessage("en", "api.t2i.title")).toBe("Image generation (T2I)");
    expect(translateMessage("en", "api.t2i.modeSkip")).toBe("Skip setup");
    expect(translateMessage("en", "api.t2i.workflowPick")).toBe("Choose API workflow JSON");
  });

  it("covers background manager copy", () => {
    expect(translateMessage("zh_CN", "background.toast.importComplete", { count: 2 })).toBe("导入 2 个背景组");
    expect(translateMessage("en", "background.resource.imageCount", { count: 1 })).toBe("1 images");
    expect(translateMessage("ja", "background.validation.nameRequired")).toContain("背景名");
    expect(translateMessage("zh_CN", "background.asset.clearImagesConfirmBody", { count: 2, name: "Room" })).toContain(
      "Room",
    );
    expect(translateMessage("en", "background.asset.selectAllBgm")).toContain("Select all");
  });

  it("covers character editor copy", () => {
    expect(translateMessage("zh_CN", "character.toast.importComplete", { count: 2 })).toBe("导入 2 个角色");
    expect(translateMessage("en", "character.validation.nameRequired")).toContain("Character");
    expect(translateMessage("ja", "character.delete.confirmBody", { name: "Nanami" })).toContain("Nanami");
    expect(
      translateMessage("en", "character.sprite.deleteConfirmBody", {
        filename: "Sprite01.webp",
        index: 1,
        name: "Nanami",
      }),
    ).toContain("Sprite01.webp");
  });

  it("covers template, chat, and plugin copy", () => {
    expect(translateMessage("zh_CN", "template.validation.charactersRequired")).toContain("角色");
    expect(translateMessage("en", "chat.clear.confirmAction")).toBe("Clear");
    expect(translateMessage("ja", "plugin.error.toggleFallback")).toContain("プラグイン");
  });
});
