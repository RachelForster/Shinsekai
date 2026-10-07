import { expect, test } from "@playwright/test";

declare global {
  interface Window {
    __agentActivityTestPhase?: number;
  }
}

for (const width of [1280, 390]) {
  test(`assistant activity and recovery at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem("shinsekai-onboarding-seen", "true");
      localStorage.setItem("shinsekai-feature-highlights-seen", "999.0.0");
      localStorage.setItem("shinsekai-language", "zh_CN");
    });
    await page.route("https://api.github.com/repos/RachelForster/Shinsekai", (route) =>
      route.fulfill({ json: { stargazers_count: 12 } }),
    );
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/#/settings/tools");
    await expect(page.getByRole("button", { name: "助手", exact: true })).toBeVisible();
    await page.evaluate(async () => {
      const url = "/src/shared/platform/platform.ts";
      const { getPlatform } = await import(/* @vite-ignore */ url);
      const platform = getPlatform();
      window.__agentActivityTestPhase = 0;
      const timestamp = new Date().toISOString();
      const session = {
        sessionId: "activity-session",
        backendId: "preview",
        backendVersion: "1",
        profileId: "basic",
        modelRef: "preview-model",
        systemPolicyRef: "agent:default",
        skillRefs: [],
        createdAt: timestamp,
      };
      const events = [
        {
          type: "activity.updated",
          payload: {
            activityId: "read",
            kind: "tool",
            name: "read",
            status: "running",
            target: "C:/session/skills/shinsekai-character-creation/SKILL.md",
          },
        },
        {
          type: "activity.updated",
          payload: {
            activityId: "read",
            kind: "tool",
            name: "read",
            status: "succeeded",
            target: "C:/session/skills/shinsekai-character-creation/SKILL.md",
          },
        },
        { type: "message.delta", payload: { messageId: "reply", delta: "正在检查本地依赖。" } },
        {
          type: "activity.updated",
          payload: {
            activityId: "shell",
            kind: "tool",
            name: "powershell",
            status: "running",
            target: "Get-Command -Name yt-dlp, ffmpeg -ErrorAction SilentlyContinue",
          },
        },
      ].map((event, index) => ({
        ...event,
        taskId: "activity-task",
        eventSeq: index + 1,
        schemaVersion: 1,
        timestamp,
      }));
      platform.agent = {
        ...platform.agent,
        listSessions: async () => ({ sessions: [session], nextCursor: null }),
        listTasks: async () => ({
          tasks: [
            {
              taskId: "activity-task",
              sessionId: session.sessionId,
              requestId: "request",
              input: { text: "创建人物，先检查需要的工具" },
              status: "running",
              createdAt: timestamp,
              updatedAt: timestamp,
              result: null,
              error: null,
            },
          ],
          nextCursor: null,
        }),
        readEvents: async (taskId: string, afterSeq: number) => {
          const end = window.__agentActivityTestPhase ? 4 : 1;
          return {
            taskId,
            nextSeq: end,
            events: events.filter((event) => event.eventSeq > afterSeq && event.eventSeq <= end),
          };
        },
      };
    });
    const entry = page.getByRole("button", { name: "助手", exact: true });
    await entry.click();
    const drawer = page.getByRole("dialog", { name: "助手", exact: true });
    const current = drawer.getByRole("status");
    await expect(current).toContainText("读取技能");
    await expect(current).toContainText("shinsekai-character-creation");
    await expect(drawer.getByText("执行过程 · 1 步", { exact: true })).toBeVisible();
    await page.evaluate(() => {
      window.__agentActivityTestPhase = 1;
    });
    await expect(current).toContainText("执行命令");
    await expect(current).toContainText("Get-Command -Name yt-dlp, ffmpeg");
    await expect(drawer.getByText("正在检查本地依赖。", { exact: true })).toBeVisible();
    await expect(drawer.getByText("执行过程 · 2 步", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`activity-${width}.png`) });
    const dimensions = await drawer
      .locator(".agent-message--assistant")
      .evaluate((element) => ({ scroll: element.scrollWidth, client: element.clientWidth }));
    expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client + 1);
    await drawer.locator(".agent-drawer__close").click();
    await entry.click();
    await expect(current).toContainText("执行命令");
    expect(errors).toEqual([]);
  });
}
