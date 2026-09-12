import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { resolveChatTheme, type ChatThemeManifest } from "../src/shared/theme/chatTheme";

function builtin(id: string): ChatThemeManifest {
  return JSON.parse(readFileSync(new URL(`../../assets/chat_ui_themes/${id}/theme.json`, import.meta.url), "utf8"));
}

function custom(tokens: ChatThemeManifest["tokens"]): ChatThemeManifest {
  return { schema: 1, id: "regression", name: { en: "Regression" }, tokens };
}

async function applyTheme(page: Page, manifest: ChatThemeManifest) {
  const { style } = resolveChatTheme(manifest, (rel) => `/theme-assets/${rel}`);
  await page.locator(".chat-stage").evaluate((element, variables) => {
    element.removeAttribute("style");
    for (const [name, value] of Object.entries(variables))
      (element as HTMLElement).style.setProperty(name, String(value));
  }, style);
}

// Use the production CSS cascade and resolver without requiring a running Python bridge.
test.beforeEach(async ({ page }) => {
  await page.route("**/theme-regression", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<html><head><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head>
      <body style="margin:0"><main class="chat-stage">
        <div class="dialog-stack"><div class="dialog-layer">Dialog text</div></div>
        <div class="input-layer" data-layout="pill">
          <button class="input-layer__press input-layer__asr-button--listening icon-button" aria-label="Microphone">Mic</button>
          <input aria-label="Message">
          <button class="input-layer__quick-submit icon-button" aria-label="Send">Send</button>
        </div>
      </main></body></html>`,
    }),
  );
  await page.route("**/theme-assets/**", (route) => route.fulfill({ status: 404, body: "Missing artwork" }));
  await page.goto("/theme-regression");
  await page.addStyleTag({ url: "/src/features/chat-stage/chat-stage.css" });
});

for (const id of ["sakura-dream", "spiritron-command"]) {
  test(`${id} preserves gradient controls with artwork, including hover`, async ({ page }) => {
    const manifest = builtin(id);
    manifest.tokens!.send = { ...manifest.tokens!.send, backgroundImage: "send.png" };
    manifest.tokens!.input = { ...manifest.tokens!.input, microphoneImage: "mic.png" };
    await applyTheme(page, manifest);
    for (const name of ["Send", "Microphone"]) {
      const control = page.getByRole("button", { name, exact: true });
      await expect(control).toHaveCSS("background-image", /url\(.+linear-gradient\(/);
      await control.hover();
      await expect(control).toHaveCSS("background-image", /url\(.+linear-gradient\(/);
      await page.mouse.move(0, 0);
    }
  });
}

test("solid send backgrounds also remain underneath artwork", async ({ page }) => {
  await applyTheme(
    page,
    custom({
      input: { layout: "pill", microphoneImage: "mic.png" },
      send: { background: "#123456", backgroundImage: "send.png" },
    }),
  );
  for (const name of ["Send", "Microphone"]) {
    const control = page.getByRole("button", { name, exact: true });
    await expect(control).toHaveCSS("background-color", "rgb(18, 52, 86)");
    await control.hover();
    await expect(control).toHaveCSS("background-color", "rgb(18, 52, 86)");
    await page.mouse.move(0, 0);
  }
});

test("idle microphone artwork survives the shared button and hover backgrounds", async ({ page }) => {
  await applyTheme(page, custom({ input: { layout: "pill", microphoneImage: "mic.png" } }));
  const mic = page.getByRole("button", { name: "Microphone", exact: true });
  await mic.evaluate((element) => element.classList.remove("input-layer__asr-button--listening"));
  await expect(mic).toHaveCSS("background-image", /url\(.+mic\.png/);
  await mic.hover();
  await expect(mic).toHaveCSS("background-image", /url\(.+mic\.png/);
});

test("listening controls respect reduced motion even on hover", async ({ page }) => {
  await applyTheme(page, custom({ input: { layout: "pill" } }));
  await page.emulateMedia({ reducedMotion: "reduce" });
  const mic = page.getByRole("button", { name: "Microphone", exact: true });
  await expect(mic).toHaveCSS("animation-name", "none");
  await mic.hover();
  await expect(mic).toHaveCSS("animation-name", "none");
});

for (const id of ["sakura-dream", "spiritron-command", "neon-night-city", "windborne-adventure"]) {
  test(`${id} retains its existing dialog padding`, async ({ page }) => {
    const manifest = builtin(id);
    await applyTheme(page, manifest);
    await expect(page.locator(".dialog-layer")).toHaveCSS("padding-left", `${manifest.tokens!.dialog!.padding}px`);
    await expect(page.locator(".dialog-layer")).toHaveCSS("padding-right", `${manifest.tokens!.dialog!.padding}px`);
  });
}

test("default, explicit inline and narrow viewport padding remain usable", async ({ page }) => {
  await applyTheme(page, custom({}));
  await expect(page.locator(".dialog-layer")).toHaveCSS("padding-left", "24px");
  await expect(page.locator(".dialog-layer")).toHaveCSS("padding-top", "20px");
  await applyTheme(page, custom({ dialog: { padding: 28, paddingInlinePx: 92 } }));
  await expect(page.locator(".dialog-layer")).toHaveCSS("padding-left", "92px");
  await expect(page.locator(".dialog-layer")).toHaveCSS("padding-top", "28px");
  await page.setViewportSize({ width: 600, height: 900 });
  await expect(page.locator(".dialog-layer")).toHaveCSS("padding-left", "16px");
});

test("zero theme inset preserves the device safe area and control stack clearance", async ({ page }) => {
  await applyTheme(page, builtin("raging-loop-simple"));
  await expect(page.locator(".input-layer")).toHaveCSS("bottom", "0px");
  const stackBottom = () =>
    page.locator(".dialog-stack").evaluate((element) => parseFloat(getComputedStyle(element).bottom));
  const before = await stackBottom();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { bottom: 34 } });
  await expect(page.locator(".input-layer")).toHaveCSS("bottom", "34px");
  expect(await stackBottom()).toBeCloseTo(before + 34, 1);
  await applyTheme(page, custom({ input: { bottomInsetPx: 60 } }));
  await expect(page.locator(".input-layer")).toHaveCSS("bottom", "60px");
});

test("empty pill radii preserve the default while explicit zero remains square", async ({ page }) => {
  for (const borderRadius of [undefined, "", "   "]) {
    await applyTheme(page, custom({ input: { layout: "pill", borderRadius } }));
    const radius = await page
      .locator(".input-layer")
      .evaluate((element) => parseFloat(getComputedStyle(element).borderTopLeftRadius));
    expect(radius).toBeGreaterThan(20);
  }
  await applyTheme(page, custom({ input: { layout: "pill", borderRadius: "0px" } }));
  await expect(page.locator(".input-layer")).toHaveCSS("border-top-left-radius", "0px");
});
