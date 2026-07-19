import { describe, expect, it } from "vitest";

import { diagnoseChatTheme } from "../../../shared/theme/chatThemeDiagnostics";
import { CHAT_THEME_SCHEMA, type ChatThemeManifest } from "../../../shared/theme/chatTheme";

function manifest(tokens: ChatThemeManifest["tokens"]): ChatThemeManifest {
  return {
    id: "diagnostic-theme",
    name: { en: "Diagnostic theme" },
    schema: CHAT_THEME_SCHEMA,
    tokens,
  };
}

describe("chat theme diagnostics", () => {
  it("reports low contrast and mobile overflow risks", () => {
    const diagnostics = diagnoseChatTheme(
      manifest({
        dialog: { background: "#ffffff", color: "#eeeeee", widthPct: 99 },
      }),
      [],
    );

    expect(diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "contrast", section: "dialog" }),
        expect.objectContaining({ code: "viewport-overflow", section: "dialog" }),
      ]),
    );
  });

  it("checks every referenced theme asset against the workbench", () => {
    const diagnostics = diagnoseChatTheme(
      {
        ...manifest({
          dialog: { frameImage: "assets/frame.svg" },
          fonts: [{ family: "Story", src: "assets/story.woff2" }],
          typewriter: { sound: "assets/type.wav" },
        }),
        preview: "preview.png",
      },
      [{ path: "assets/frame.svg" }, { path: "assets/type.wav" }],
    );

    expect(diagnostics.filter((item) => item.code === "missing-asset").map((item) => item.detail)).toEqual([
      "preview.png",
      "assets/story.woff2",
    ]);
  });

  it("skips asset checks while the asset list is still loading", () => {
    const diagnostics = diagnoseChatTheme(manifest({ dialog: { backgroundImage: "assets/bg.png" } }));
    expect(diagnostics).toEqual([]);
  });
});
