import { describe, expect, it } from "vitest";

import { patchChatThemeTokenPath } from "../../../features/chat-stage/theme/useChatThemeCustomizer";
import { chatThemeEditorFieldPaths } from "../../../shared/theme/chatThemeSchema";

describe("chat theme editor schema", () => {
  it("covers every editable top-level token family and state surface", () => {
    expect(chatThemeEditorFieldPaths).toEqual(
      expect.arrayContaining([
        "global.themeColor",
        "global.windowScale",
        "fonts",
        "dialog.frameImage",
        "dialog.opacity",
        "dialog.scale",
        "dialog.fontFamily",
        "options.hover.background",
        "options.active.background",
        "input.sendPlacement",
        "toolbar.placement",
        "send.background",
        "name.fontFamily",
        "logs.panel.frameImage",
        "logs.line.hover.background",
        "logs.fileItem.active.background",
        "logs.levels.error.color",
        "typewriter.sound",
      ]),
    );
  });

  it("patches nested token paths and prunes empty inherited blocks", () => {
    const withHover = patchChatThemeTokenPath({}, "options.hover.background", "#fff");
    expect(withHover).toEqual({ options: { hover: { background: "#fff" } } });

    const inherited = patchChatThemeTokenPath(withHover, "options.hover.background", undefined);
    expect(inherited).toEqual({});
  });
});
