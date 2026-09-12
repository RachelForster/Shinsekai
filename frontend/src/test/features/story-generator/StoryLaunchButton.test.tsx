import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StoryLaunchButton } from "../../../features/story-generator/components/StoryLaunchButton";
import { I18nProvider, type FrontendLanguage } from "../../../shared/i18n";

const { launchChat, getChatRuntimeStatus, getChatSnapshot, startStorySession, showChatSurface, prepareStoryLaunch } =
  vi.hoisted(() => ({
    prepareStoryLaunch: vi.fn(),
    launchChat: vi.fn(),
    getChatRuntimeStatus: vi.fn(),
    getChatSnapshot: vi.fn(),
    startStorySession: vi.fn(),
    showChatSurface: vi.fn(),
  }));
vi.mock("../../../entities/chat/repository", () => ({
  launchChat,
  getChatRuntimeStatus,
  getChatSnapshot,
  chatQueryKey: ["chat"],
}));
vi.mock("../../../entities/story/repository", () => ({
  startStorySession,
  prepareStoryLaunch,
  storyLibraryQueryKey: ["story-library"],
}));
vi.mock("../../../shared/desktop/chatWindow", () => ({ showChatSurface }));
vi.mock("../../../features/chat-startup/ChatInitializationDialog", () => ({ ChatInitializationDialog: () => null }));

function renderButton(historyPath = "", language: FrontendLanguage = "zh_CN") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider language={language}>
        <MemoryRouter>
          <StoryLaunchButton storyPath="story/draft.json" historyPath={historyPath} disabled={false} />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("story launch", () => {
  it("localizes the default launch action and active-chat error", async () => {
    getChatRuntimeStatus.mockResolvedValue({ state: "running" });
    renderButton("", "en");
    fireEvent.click(screen.getByRole("button", { name: "Play story" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("End the current chat before playing a story.");
    expect(launchChat).not.toHaveBeenCalled();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getChatSnapshot.mockResolvedValue({ sessionId: "session-1", runtimeMode: "react" });
    getChatRuntimeStatus.mockResolvedValue({ state: "idle" });
    prepareStoryLaunch.mockImplementation((_storyPath: string, historyPath: string) =>
      Promise.resolve({
        templateId: "",
        characters: ["小玲"],
        backgroundName: "旧校舍",
        system: "人物设定",
        historyPath,
        resetHistory: !historyPath,
      }),
    );
    launchChat.mockResolvedValue({ sessionId: "session-1", runtimeMode: "react" });
    startStorySession.mockResolvedValue({ story: { storyId: "story-1" } });
  });
  it("initializes a fresh history, attaches the generated draft, then opens chat", async () => {
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    await waitFor(() => expect(showChatSurface).toHaveBeenCalled());
    expect(launchChat).toHaveBeenCalledWith(
      expect.objectContaining({ templateId: "", characters: ["小玲"], backgroundName: "旧校舍", resetHistory: true }),
      expect.anything(),
    );
    expect(startStorySession).toHaveBeenCalledWith("story/draft.json");
    expect(startStorySession.mock.invocationCallOrder[0]).toBeGreaterThan(launchChat.mock.invocationCallOrder[0]);
  });
  it("continues the selected save without resetting its history", async () => {
    renderButton("data/chat_history/saved");
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    await waitFor(() => expect(showChatSurface).toHaveBeenCalled());
    expect(prepareStoryLaunch).toHaveBeenCalledWith("story/draft.json", "data/chat_history/saved");
    expect(launchChat).toHaveBeenCalledWith(
      expect.objectContaining({
        historyPath: "data/chat_history/saved",
        resetHistory: false,
      }),
      expect.anything(),
    );
  });
  it("does not attach a story to someone else's running chat", async () => {
    getChatRuntimeStatus.mockResolvedValue({ state: "running" });
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请先结束当前聊天");
    expect(launchChat).not.toHaveBeenCalled();
    expect(startStorySession).not.toHaveBeenCalled();
  });
  it("retries attachment after a failure without creating another history", async () => {
    startStorySession.mockRejectedValueOnce(new Error("立绘尚未准备好"));
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("立绘尚未准备好");
    expect(showChatSurface).not.toHaveBeenCalled();
    getChatRuntimeStatus.mockResolvedValue({ state: "running" });
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    await waitFor(() => expect(showChatSurface).toHaveBeenCalled());
    expect(launchChat).toHaveBeenCalledTimes(1);
  });
  it("preserves attachment retry after remount with a new query cache", async () => {
    startStorySession.mockRejectedValueOnce(new Error("network unavailable"));
    const first = renderButton();
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    await screen.findByRole("alert");
    first.unmount();
    getChatRuntimeStatus.mockResolvedValue({ state: "running" });
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    await waitFor(() => expect(showChatSurface).toHaveBeenCalled());
    expect(launchChat).toHaveBeenCalledTimes(1);
    expect(startStorySession).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem("story.pending-attachment.v1")).toBeNull();
  });
  it.each(["changed-session", "changed-save", "closing"])("rejects a stale retry after %s", async (change) => {
    startStorySession.mockRejectedValueOnce(new Error("network unavailable"));
    const first = renderButton();
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    await screen.findByRole("alert");
    first.unmount();
    getChatRuntimeStatus.mockResolvedValue({ state: change === "closing" ? "closing" : "running" });
    if (change === "changed-session") getChatSnapshot.mockResolvedValue({ sessionId: "session-2" });
    renderButton(change === "changed-save" ? "different-save" : "");
    fireEvent.click(screen.getByRole("button", { name: "运行剧本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请先结束当前聊天");
    expect(startStorySession).toHaveBeenCalledTimes(1);
  });
});
