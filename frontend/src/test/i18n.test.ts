import { describe, expect, it } from "vitest";

import { translateMessage } from "../shared/i18n";

describe("translateMessage", () => {
  it("returns localized messages for supported languages", () => {
    expect(translateMessage("zh_CN", "nav.plugins")).toBe("插件");
    expect(translateMessage("en", "nav.plugins")).toBe("Plugins");
    expect(translateMessage("ja", "nav.plugins")).toBe("プラグイン");
  });

  it("interpolates named values", () => {
    expect(translateMessage("zh_CN", "plugin.installed.count", { count: 3 })).toBe("3 个插件");
    expect(translateMessage("en", "plugin.installed.count", { count: 3 })).toBe("3 plugins");
  });

  it("covers schema settings page copy", () => {
    expect(translateMessage("zh_CN", "api.title")).toBe("API 配置");
    expect(translateMessage("en", "system.toast.saved")).toBe("System settings saved");
    expect(translateMessage("ja", "form.jsonInvalid")).toContain("JSON");
  });

  it("covers T2I setup copy without falling back to raw keys", () => {
    expect(translateMessage("en", "api.t2i.title")).toBe("Image generation (T2I)");
    expect(translateMessage("en", "api.t2i.modeSkip")).toBe("Skip setup");
    expect(translateMessage("en", "api.t2i.workflowPick")).toBe("Choose workflow JSON");
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
