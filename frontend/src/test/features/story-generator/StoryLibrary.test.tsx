import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StoryLibrary } from "../../../features/story-generator/components/StoryLibrary";
import { I18nProvider } from "../../../shared/i18n";

const { listStories, deleteStory } = vi.hoisted(() => ({ listStories: vi.fn(), deleteStory: vi.fn() }));
vi.mock("../../../entities/story/repository", () => ({
  listStories,
  deleteStory,
  storyLibraryQueryKey: ["story-library"],
}));
vi.mock("../../../features/story-generator/components/StoryLaunchButton", () => ({
  StoryLaunchButton: () => <button>Play</button>,
}));
vi.mock("../../../features/story-generator/editor/StoryEditor", () => ({ StoryEditor: () => null }));

const versions = [1, 2].map((version) => ({
  id: "same-story",
  title: "旧校舍",
  version,
  storyPath: `version-${version}.json`,
  canEditGraph: version === 2,
  characters: [],
  backgrounds: [],
  historyPath: "",
  updatedAt: version,
}));

function renderLibrary() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="zh_CN">
        <StoryLibrary onCreate={vi.fn()} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return invalidate;
}

async function chooseFirstVersion() {
  const cards = await screen.findAllByRole("article");
  fireEvent.click(within(cards[0]).getByRole("button", { name: "删除" }));
  return screen.getByRole("dialog", { name: "删除剧本版本" });
}

describe("story version deletion", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    listStories.mockResolvedValue(versions);
  });

  it("lets users cancel without deleting even a legacy version", async () => {
    renderLibrary();
    const dialog = await chooseFirstVersion();
    expect(within(dialog).getByText(/版本 1 及其全部关联对话和存档/)).toBeVisible();
    expect(deleteStory).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(deleteStory).not.toHaveBeenCalled();
  });

  it("deletes only the chosen version and refreshes stories and conversations", async () => {
    deleteStory.mockImplementation(async () => {
      listStories.mockResolvedValue([versions[1]]);
    });
    const invalidate = renderLibrary();
    const dialog = await chooseFirstVersion();
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deleteStory).toHaveBeenCalledTimes(1);
    expect(deleteStory).toHaveBeenCalledWith("version-1.json");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("版本 2")).toBeVisible();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["story-library"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["chat"] });
  });

  it("prevents duplicate requests and keeps failures visible for retry", async () => {
    let reject: (error: Error) => void = () => {};
    deleteStory.mockImplementationOnce(
      () =>
        new Promise((_resolve, fail) => {
          reject = fail;
        }),
    );
    renderLibrary();
    const dialog = await chooseFirstVersion();
    const confirm = within(dialog).getByRole("button", { name: "删除" });
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeVisible();
    reject(new Error("请先关闭该剧本版本的聊天"));
    expect(await screen.findByRole("alert")).toHaveTextContent("请先关闭该剧本版本的聊天");
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(confirm).toBeEnabled();
    deleteStory.mockImplementationOnce(async () => {
      listStories.mockResolvedValue([versions[1]]);
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deleteStory).toHaveBeenCalledTimes(2);
  });
});
