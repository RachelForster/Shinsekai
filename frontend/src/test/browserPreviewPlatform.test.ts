import { afterEach, describe, expect, it, vi } from "vitest";

import { createBrowserPreviewPlatform } from "../shared/platform/browserPreviewPlatform";

describe("browser preview platform chat themes", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("switches active theme and serves matching manifests and legacy payloads", async () => {
    const platform = createBrowserPreviewPlatform();

    await expect(platform.chat.getActiveThemeId()).resolves.toBe("classic-dark");

    const themes = await platform.chat.listThemes();
    expect(themes.map((theme) => theme.id)).toEqual(["classic-dark", "light-paper"]);

    const classicManifest = await platform.chat.getThemeManifest("classic-dark");
    expect(classicManifest.tokens.global?.themeColor).toBe("#644ae3");
    expect(classicManifest.tokens.logs?.code?.background).toBe("rgba(8,9,14,0.9)");

    const classicTheme = await platform.chat.getTheme();
    expect(classicTheme.themeColor).toBe("#644ae3");

    await platform.chat.setActiveThemeId("light-paper");

    await expect(platform.chat.getActiveThemeId()).resolves.toBe("light-paper");
    const lightManifest = await platform.chat.getThemeManifest("light-paper");
    expect(lightManifest.tokens.dialog?.background).toBe("rgba(250,248,244,0.92)");
    expect(lightManifest.tokens.logs?.code?.background).toBe("rgba(253,251,255,0.95)");

    const lightTheme = await platform.chat.getTheme();
    expect(lightTheme.themeColor).toBe("#c77dff");
    expect(JSON.stringify(lightTheme.raw)).toContain("rgba(250,248,244,0.92)");
  });

  it("adds uploaded preview themes as user themes and protects builtins from deletion", async () => {
    const platform = createBrowserPreviewPlatform();

    const uploaded = await platform.chat.uploadTheme(
      new File(["theme"], "mint-breeze.zip", { type: "application/zip" }),
    );
    expect(uploaded.id).toBe("mint-breeze");
    expect(uploaded.source).toBe("user");

    const themes = await platform.chat.listThemes();
    expect(themes.find((theme) => theme.id === "mint-breeze")?.source).toBe("user");

    await expect(platform.chat.deleteTheme("classic-dark")).rejects.toThrow("内置主题不能删除。");

    await platform.chat.deleteTheme("mint-breeze");
    const nextThemes = await platform.chat.listThemes();
    expect(nextThemes.find((theme) => theme.id === "mint-breeze")).toBeUndefined();
  });

  it("advances option and message commands through preview runtime states", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const seenStatuses: string[] = [];
    const unsubscribe = platform.chat.subscribe((snapshot) => {
      seenStatuses.push(snapshot.status);
    });

    const optionPromise = platform.chat.command({ payload: "继续", type: "submit-option" });
    await vi.advanceTimersByTimeAsync(120);
    const optionSnapshot = await optionPromise;
    expect(optionSnapshot.status).toBe("generating");
    expect(optionSnapshot.options).toEqual([]);

    await vi.advanceTimersByTimeAsync(650);
    const afterOptionPromise = platform.chat.getSnapshot();
    await vi.advanceTimersByTimeAsync(120);
    const afterOption = await afterOptionPromise;
    expect(afterOption.status).toBe("idle");
    expect(afterOption.dialogText).toContain("已选择");

    const sendPromise = platform.chat.command({ payload: "你好", type: "send-message" });
    await vi.advanceTimersByTimeAsync(120);
    const sendingSnapshot = await sendPromise;
    expect(sendingSnapshot.status).toBe("streaming");
    expect(sendingSnapshot.characterName).toBe("你");
    expect(sendingSnapshot.dialogText).toBe("你好");
    expect(sendingSnapshot.inputDraft).toBe("");

    await vi.advanceTimersByTimeAsync(700);
    expect(seenStatuses).toContain("speaking");

    await vi.advanceTimersByTimeAsync(700);
    const finalSnapshotPromise = platform.chat.getSnapshot();
    await vi.advanceTimersByTimeAsync(120);
    const finalSnapshot = await finalSnapshotPromise;
    expect(finalSnapshot.status).toBe("idle");
    expect(finalSnapshot.characterName).toBe("Nanami");
    expect(finalSnapshot.dialogText).toBe("收到：你好");

    unsubscribe();
  });

  it("clears closed-session markers when preview realtime commands resume interaction", async () => {
    vi.useFakeTimers();
    const platform = createBrowserPreviewPlatform();
    const seenSnapshots: Array<{ notificationText?: string; sessionClosedReason?: string; status: string }> = [];
    const unsubscribe = platform.chat.subscribe((snapshot) => {
      seenSnapshots.push({
        notificationText: snapshot.notificationText,
        sessionClosedReason: snapshot.sessionClosedReason,
        status: snapshot.status,
      });
    });

    const closePromise = platform.chat.close();
    await vi.advanceTimersByTimeAsync(120);
    const closedSnapshot = await closePromise;
    expect(closedSnapshot.sessionClosedReason).toBe("聊天会话已结束。");
    expect(closedSnapshot.notificationText).toBe("聊天会话已结束。");

    const resumePromise = platform.chat.command({ type: "resume-asr" });
    await vi.advanceTimersByTimeAsync(120);
    const resumedSnapshot = await resumePromise;

    expect(resumedSnapshot.status).toBe("listening");
    expect(resumedSnapshot.sessionClosedReason).toBe("");
    expect(resumedSnapshot.notificationText).toBe("");
    expect(
      seenSnapshots.some(
        (snapshot) =>
          snapshot.status === "idle" &&
          snapshot.sessionClosedReason === "聊天会话已结束。" &&
          snapshot.notificationText === "聊天会话已结束。",
      ),
    ).toBe(true);
    expect(
      seenSnapshots.some(
        (snapshot) =>
          snapshot.status === "listening" && snapshot.sessionClosedReason === "" && snapshot.notificationText === "",
      ),
    ).toBe(true);

    unsubscribe();
  });
});
