import { expect, test, type Page } from "@playwright/test";

declare global {
  interface Window {
    CUJ: { holdEnd: boolean; failNextEnd: boolean; stopCalls: number; launchCalls: number; finishEnd: () => void };
  }
}

// Both browser views use the real app and share a controlled IPC session.
// No real provider, LAN listener, or user conversation is changed by these journeys.
test.setTimeout(90_000);
test.beforeEach(async ({ context, page }) => {
  await context.route("**/mobile-chat-cuj*", (route) =>
    route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
      <body><div id="root"></div><script type="module">
      import RefreshRuntime from "/@react-refresh";
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {};
      window.$RefreshSig$ = () => type => type;
      window.__vite_plugin_react_preamble_installed__ = true;
      import { createBrowserPreviewPlatform } from "/src/shared/platform/browserPreviewPlatform.ts";
      if (window.opener?.CUJ) {
        window.CUJ = window.opener.CUJ;
      } else {
        const platform = createBrowserPreviewPlatform();
        const launch = platform.chat.launch.bind(platform.chat);
        const close = platform.chat.close.bind(platform.chat);
        const snapshot = platform.chat.getSnapshot.bind(platform.chat);
        const subscribe = platform.chat.subscribeEvents.bind(platform.chat);
        for (const [id, title] of [["a", "晚间散步"], ["b", "清晨咖啡"]]) {
          await launch({ characters: ["Nanami"], historyPath: "cuj-" + id, conversationTitle: title });
          await close();
        }
        let session = 0;
        let phoneEnabled = false;
        const fixture = { platform, stopCalls: 0, launchCalls: 0, holdEnd: false, failNextEnd: false };
        const decorate = value => ({
          ...value, runtimeMode: "react", sessionId: "cuj-session-" + session,
          mobileAccess: value.chatProcessRunning && phoneEnabled ? {
            enabled: true, host: "127.0.0.1", httpPort: Number(location.port), websocketPort: 8790,
            url: location.origin + "/mobile-chat-cuj?phone=1#/chat-stage",
            websocketUrl: "ws://127.0.0.1:8790/ws",
            qrCodeDataUrl: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='128' height='128'%3E%3Crect width='128' height='128' fill='white'/%3E%3C/svg%3E"
          } : undefined,
        });
        platform.chat.getSnapshot = async () => decorate(await snapshot());
        platform.chat.subscribeEvents = listener => subscribe(event => listener(
          event.type === "snapshot" ? { ...event, snapshot: decorate(event.snapshot) } : event
        ));
        platform.chat.launch = async (payload, options) => {
          fixture.launchCalls++;
          phoneEnabled = Boolean(payload.enableMobileAccess);
          session++;
          return decorate(await launch(payload, options));
        };
        platform.chat.close = async (options) => {
          if (options?.expectedSessionId !== undefined && options.expectedSessionId !== "cuj-session-" + session) {
            throw new Error("The current chat has changed.");
          }
          fixture.stopCalls++;
          if (fixture.failNextEnd) {
            fixture.failNextEnd = false;
            throw new Error("暂时无法结束对话，请重试");
          }
          if (fixture.holdEnd) await new Promise(resolve => { fixture.finishEnd = resolve; });
          return decorate(await close());
        };
        window.CUJ = fixture;
      }
      window.__SHINSEKAI_IPC__ = window.CUJ.platform;
      localStorage.setItem("shinsekai.chat.mobile-access.v1", "true");
      await import("/src/main.tsx");
      </script></body></html>`,
    }),
  );
  await page.goto("/mobile-chat-cuj#/settings/templates");
  await expect(page.getByRole("heading", { name: "晚间散步", exact: true })).toBeVisible({ timeout: 60_000 });
});

function card(page: Page, name: string) {
  return page.locator(".conversation-card").filter({ has: page.getByRole("heading", { name, exact: true }) });
}

async function launchFirst(page: Page) {
  await card(page, "晚间散步").getByRole("button", { name: "继续聊天", exact: true }).click();
  const qr = page.getByRole("dialog", { name: "手机访问已开启" });
  await expect(qr).toBeVisible();
  await qr.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(page.getByRole("heading", { name: "当前正在聊天：晚间散步" })).toBeVisible();
}

test("closing and reopening QR keeps phone chat alive, then ending enables another mobile chat", async ({ page }) => {
  await launchFirst(page);
  if (process.env.SHINSEKAI_CUJ_SCREENSHOT) {
    await page.locator(".conversation-library").screenshot({ path: process.env.SHINSEKAI_CUJ_SCREENSHOT });
  }
  const popup = page.waitForEvent("popup");
  await page.evaluate(() => window.open("/mobile-chat-cuj?phone=1#/chat-stage"));
  const phone = await popup;
  await phone.setViewportSize({ width: 390, height: 844 });
  const input = phone.locator(".input-layer__input");
  await expect(input).toBeEnabled();
  await input.fill("二维码关闭后仍可以聊天");
  await phone.getByRole("button", { name: "发送", exact: true }).click();
  await expect(phone.locator(".dialog-layer__text")).toContainText("二维码关闭后仍可以聊天");
  await page.getByRole("button", { name: "显示二维码" }).click();
  const qr = page.getByRole("dialog", { name: "手机访问已开启" });
  await expect(qr.getByRole("img")).toBeVisible();
  await qr.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "结束对话", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "结束对话" });
  await expect(confirmation).toContainText("结束后手机连接将断开，聊天记录保留，可稍后继续");
  await confirmation.getByRole("button", { name: "取消" }).click();
  await expect(input).toBeEnabled();
  await page.getByRole("button", { name: "结束对话", exact: true }).click();
  await page.evaluate(() => {
    window.CUJ.holdEnd = true;
  });
  await confirmation.getByRole("button", { name: "结束对话", exact: true }).click();
  await expect(confirmation.getByRole("button", { name: "正在结束…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "新建聊天" })).toBeDisabled();
  await expect(card(page, "清晨咖啡").getByRole("button", { name: "继续聊天", exact: true })).toBeDisabled();
  await expect.poll(() => page.evaluate(() => window.CUJ.stopCalls)).toBe(1);
  await page.evaluate(() => {
    window.CUJ.finishEnd();
  });
  await expect(confirmation).toBeHidden();
  await expect(phone.locator(".chat-stage__notification")).toContainText("聊天会话已结束");
  await expect(page.getByRole("button", { name: "新建聊天" })).toBeEnabled();
  await expect(card(page, "晚间散步")).toBeVisible();
  await card(page, "清晨咖啡").getByRole("button", { name: "继续聊天", exact: true }).click();
  await expect(qr).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前正在聊天：清晨咖啡" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.CUJ.launchCalls)).toBe(2);
});

test("a failed end keeps the current chat and provides a working retry", async ({ page }) => {
  await launchFirst(page);
  await page.evaluate(() => {
    window.CUJ.failNextEnd = true;
  });
  await page.getByRole("button", { name: "结束对话", exact: true }).click();
  const confirmation = page.getByRole("dialog", { name: "结束对话" });
  await confirmation.getByRole("button", { name: "结束对话", exact: true }).click();
  await expect(confirmation.getByRole("alert")).toContainText("暂时无法结束对话，请重试");
  await expect(page.getByRole("heading", { name: "当前正在聊天：晚间散步" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建聊天" })).toBeDisabled();
  await confirmation.getByRole("button", { name: "重试结束" }).click();
  await expect(confirmation).toBeHidden();
  await expect(page.getByRole("button", { name: "新建聊天" })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => window.CUJ.stopCalls)).toBe(2);
});

test("current chat controls fit a narrow management window and reopen local chat", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await launchFirst(page);
  const panel = page.getByRole("region", { name: "当前对话" });
  for (const name of ["显示二维码", "打开聊天", "结束对话"]) {
    await expect(panel.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.getByRole("button", { name: "打开聊天" }).click();
  await expect(page).toHaveURL(/#\/chat$/);
  await expect(page.locator(".input-layer__input")).toBeEnabled();
});
