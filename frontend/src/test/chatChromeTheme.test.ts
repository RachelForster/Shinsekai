import { describe, expect, it } from "vitest";

import { parseChatChromeTheme } from "../shared/theme/chatChromeTheme";

describe("parseChatChromeTheme", () => {
  it("maps allowed visual declarations to chat CSS variables", () => {
    const style = parseChatChromeTheme({
      raw: {
        dialog_label: {
          extra_qss:
            "background-color: rgba(50,50,50,200); color: #fff; width: 999px; border-radius: 12px;",
        },
        dialog_offset_y: 16,
        dialog_padding: 28,
        dialog_width_pct: 72,
        option_row: {
          hover_extra_qss: "background-color: rgba(90,90,90,180); font-size: 99px;",
        },
        options_gap: 14,
      },
      themeColor: "rgba(10,20,30,128)",
    });

    expect(style["--chat-dialog-background"]).toBe("rgba(50, 50, 50, 0.784)");
    expect(style["--chat-dialog-color"]).toBe("#fff");
    expect(style["--chat-dialog-border-radius"]).toBe("12px");
    expect(style["--chat-dialog-width"]).toBe("min(72vw, 980px)");
    expect(style["--chat-dialog-padding"]).toBe("28px");
    expect(style["--chat-dialog-offset-y"]).toBe("16px");
    expect(style["--chat-options-gap"]).toBe("14px");
    expect(style["--chat-option-hover-background"]).toBe("rgba(90, 90, 90, 0.706)");
    expect(style["--chat-theme-color"]).toBe("rgba(10, 20, 30, 0.502)");
    expect(Object.values(style)).not.toContain("999px");
    expect(Object.values(style)).not.toContain("99px");
  });

  it("clamps layout values and ignores unsafe background URLs", () => {
    const style = parseChatChromeTheme({
      raw: {
        dialog_label: {
          extra_qss: "background: url(file:///tmp/bg.png); box-shadow: 0 8px 20px rgba(0,0,0,.4);",
        },
        dialog_offset_y: 999,
        dialog_padding: 500,
        dialog_width_pct: 4,
        options_gap: -4,
      },
      themeColor: "",
    });

    expect(style["--chat-dialog-background"]).toBeUndefined();
    expect(style["--chat-dialog-box-shadow"]).toBe("0 8px 20px rgba(0,0,0,.4)");
    expect(style["--chat-dialog-offset-y"]).toBe("240px");
    expect(style["--chat-dialog-padding"]).toBe("72px");
    expect(style["--chat-dialog-width"]).toBe("min(30vw, 980px)");
    expect(style["--chat-options-gap"]).toBe("0px");
  });
});
