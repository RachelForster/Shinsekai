import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MusicCoverPage } from "../../../features/music-cover/MusicCoverPage";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const mockSaveMusicCoverConfig = vi.fn();
const mockSearchMusicCover = vi.fn();
const mockRunMusicCover = vi.fn();

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
}));

vi.mock("../../../entities/music-cover/repository", () => ({
  runMusicCover: (input: unknown, options: unknown) => mockRunMusicCover(input, options),
  saveMusicCoverConfig: (input: unknown) => mockSaveMusicCoverConfig(input),
  searchMusicCover: (input: unknown) => mockSearchMusicCover(input),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MusicCoverPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("MusicCoverPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mockSaveMusicCoverConfig.mockImplementation(async (input) => ({
      message: "saved",
      systemConfig: { ...sampleConfig.system_config, ...input },
    }));
    mockSearchMusicCover.mockResolvedValue({ log: "search ok" });
    mockRunMusicCover.mockResolvedValue({ audioPath: "/tmp/output/cover.wav", log: "run ok" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("saves pipeline config and runs search/run actions with the current draft", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "流水线与工具路径" })).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("./data/music_cover"), { target: { value: "/tmp/music" } });
    fireEvent.click(screen.getByRole("button", { name: "保存翻唱流水线配置" }));

    await waitFor(() =>
      expect(mockSaveMusicCoverConfig).toHaveBeenCalledWith(
        expect.objectContaining({ music_cover_work_dir: "/tmp/music" }),
      ),
    );

    fireEvent.change(screen.getByPlaceholderText("搜索词或 URL"), { target: { value: "test song" } });
    fireEvent.click(screen.getByRole("button", { name: "预览搜索结果" }));

    await waitFor(() => expect(mockSearchMusicCover).toHaveBeenCalledWith({ query: "test song", source: "youtube" }));

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "执行完整流水线" }));

    await waitFor(() =>
      expect(mockRunMusicCover).toHaveBeenCalledWith(
        { pickIndex: 0, query: "test song", skipRvc: true, source: "youtube" },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    expect(await screen.findByText("cover.wav")).toBeInTheDocument();
  });
});
