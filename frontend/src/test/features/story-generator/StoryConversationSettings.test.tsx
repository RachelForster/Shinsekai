import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { StoryConversationSettings } from "../../../features/story-generator/StoryConversationSettings";
import { I18nProvider } from "../../../shared/i18n";
const { listStories } = vi.hoisted(() => ({ listStories: vi.fn() }));
vi.mock("../../../entities/story/repository", () => ({
  storyLibraryQueryKey: ["story-library"],
  listStories,
}));
vi.mock("../../../entities/chat/repository", () => ({
  conversationsQueryKey: ["chat", "conversations"],
  listConversations: async () => [
    { id: "story-chat", kind: "story", storyPath: "original.json", historyPath: "save", hasSettings: true },
  ],
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
});
