import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { StoryConversationSettings } from "../../../features/story-generator/StoryConversationSettings";
import { I18nProvider } from "../../../shared/i18n";
const { listStories, updateConversationSettings } = vi.hoisted(() => ({
  listStories: vi.fn(),
  updateConversationSettings: vi.fn(),
}));
vi.mock("../../../entities/story/repository", () => ({
  storyLibraryQueryKey: ["story-library"],
  listStories,
}));
vi.mock("../../../entities/chat/repository", () => ({
  conversationsQueryKey: ["chat", "conversations"],
  listConversations: async () => [
    { id: "story-chat", kind: "story", storyPath: "original.json", historyPath: "save", hasSettings: true },
  ],
  updateConversationSettings,
}));
vi.mock("../../../features/story-generator/components/StoryFeatureGate", () => ({
  StoryFeatureGate: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("../../../features/story-generator/editor/StoryEditor", () => ({
  StoryEditor: ({ storyPath }: { storyPath: string }) => <div data-testid="node-editor">{storyPath}</div>,
}));
vi.mock("../../../features/story-generator/components/StoryLaunchButton", () => ({
  StoryLaunchButton: ({ historyPath, conversationId }: { historyPath: string; conversationId: string }) => (
    <button>
      {historyPath}:{conversationId}
    </button>
  ),
}));
describe("story conversation settings", () => {
  it("keeps the saved conversation separate from full-plot editing", async () => {
    listStories.mockResolvedValue([{ storyPath: "original.json", canEditGraph: true }]);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="en">
          <StoryConversationSettings conversationId="story-chat" />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "save:story-chat" })).toBeVisible();
    expect(screen.queryByTestId("node-editor")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Open story editor (includes later plot)" }));
    expect(screen.getByTestId("node-editor")).toHaveTextContent("original.json");
  });
  it("keeps legacy conversations playable without offering the editor", async () => {
    listStories.mockResolvedValue([{ storyPath: "original.json", canEditGraph: false }]);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="en">
          <StoryConversationSettings conversationId="story-chat" />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Node editing is unavailable for this story. You can still play it.")).toBeVisible();
    expect(screen.getByRole("button", { name: "save:story-chat" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Open story editor (includes later plot)" })).not.toBeInTheDocument();
  });
  it("updates memory isolation mode and auto outfit switch for a story save", async () => {
    listStories.mockResolvedValue([{ storyPath: "original.json", canEditGraph: false }]);
    updateConversationSettings.mockResolvedValue({
      id: "story-chat",
      kind: "story",
      storyPath: "original.json",
      historyPath: "save",
      hasSettings: true,
      memoryMode: "isolated",
      autoOutfitSwitch: false,
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="en">
          <StoryConversationSettings conversationId="story-chat" />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "save:story-chat" })).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: "Allow automatic outfit switching" }));
    await waitFor(() =>
      expect(updateConversationSettings).toHaveBeenCalledWith("story-chat", { autoOutfitSwitch: false }),
    );
    const mode = screen.getByRole("combobox", { name: "Long-term memory isolation" });
    await waitFor(() => expect(mode).toBeEnabled());
    fireEvent.click(mode);
    fireEvent.click(screen.getByRole("option", { name: "Shared across saves" }));
    await waitFor(() =>
      expect(updateConversationSettings).toHaveBeenCalledWith("story-chat", { memoryMode: "shared" }),
    );
  });
  it("shows the saved setting again when an update fails", async () => {
    listStories.mockResolvedValue([{ storyPath: "original.json", canEditGraph: false }]);
    updateConversationSettings.mockRejectedValueOnce(new Error("Could not save settings"));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="en">
          <StoryConversationSettings conversationId="story-chat" />
        </I18nProvider>
      </QueryClientProvider>,
    );
    const mode = await screen.findByRole("combobox", { name: "Long-term memory isolation" });
    fireEvent.click(mode);
    fireEvent.click(screen.getByRole("option", { name: "Shared across saves" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save settings");
    expect(mode).toHaveTextContent("Isolated per save (Recommended)");
  });
});
