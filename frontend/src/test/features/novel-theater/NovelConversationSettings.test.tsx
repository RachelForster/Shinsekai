import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NovelConversationSettings } from "../../../features/novel-theater/NovelConversationSettings";
import { I18nProvider } from "../../../shared/i18n";
import type { ConversationSummary } from "../../../shared/platform/types";

const mocks = vi.hoisted(() => ({
  listCharacters: vi.fn(),
  listConversations: vi.fn(),
  prepareConversation: vi.fn(),
  extractNovelCast: vi.fn(),
  saveNovelCasting: vi.fn(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: mocks.listCharacters,
}));

vi.mock("../../../entities/chat/repository", () => ({
  conversationsQueryKey: ["chat", "conversations"],
  listConversations: mocks.listConversations,
  prepareConversation: mocks.prepareConversation,
}));

vi.mock("../../../entities/novel/repository", () => ({
  extractNovelCast: mocks.extractNovelCast,
  saveNovelCasting: mocks.saveNovelCasting,
}));

const baseConversation: ConversationSummary = {
  id: "conv-novel-1",
  title: "Rainy Station",
  characters: ["Alice"],
  preview: "",
  updatedAt: 1000,
  kind: "novel",
  storyPath: "",
  novelDocId: "doc-1",
  behaviorId: "novel_theater",
  novelNameMode: "story",
  castEntries: [{ sourceName: "Lin Zhixia", aliases: ["Xiaxia"], targetCharacter: "Alice", role: "protagonist" }],
  historyPath: "h/novel-1.json",
  hasSettings: true,
};

describe("NovelConversationSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listCharacters.mockResolvedValue([{ name: "Alice", sprites: [] }]);
    mocks.listConversations.mockResolvedValue([baseConversation]);
    mocks.prepareConversation.mockResolvedValue({ nameMode: "story" });
    mocks.saveNovelCasting.mockResolvedValue({ ...baseConversation, novelNameMode: "actor" });
  });

  it("renders naming mode toggle with help badge and forwards nameMode on save", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <NovelConversationSettings conversation={baseConversation} />
        </I18nProvider>
      </QueryClientProvider>,
    );

    const storyRadio = await screen.findByRole("radio", { name: "Keep novel names" });
    const actorRadio = screen.getByRole("radio", { name: "Use actor names" });
    expect(storyRadio).toBeChecked();
    expect(actorRadio).not.toBeChecked();

    const helpButton = screen.getByRole("button", { name: "About character naming modes" });
    expect(helpButton).toHaveAttribute("aria-describedby");

    fireEvent.click(actorRadio);
    fireEvent.click(screen.getByRole("button", { name: "Save casting" }));

    await waitFor(() =>
      expect(mocks.saveNovelCasting).toHaveBeenCalledWith(
        "conv-novel-1",
        [
          {
            sourceName: "Lin Zhixia",
            aliases: ["Xiaxia"],
            targetCharacter: "Alice",
            role: "protagonist",
            silhouetteUntilRevealed: false,
          },
        ],
        "actor",
      ),
    );
    expect(await screen.findByText("Casting saved")).toBeVisible();
  });
});
