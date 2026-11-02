import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatThemeCustomizerPage } from "../../../features/chat-stage/theme/ChatThemeCustomizerPage";
import { configQueryKey } from "../../../entities/config/repository";
import { I18nProvider } from "../../../shared/i18n";
import type { ChatThemeManifest, ChatThemeSummary } from "../../../shared/theme/chatTheme";
import { ToastProvider } from "../../../shared/ui";

const baseManifest: ChatThemeManifest = {
  schema: 1,
  id: "windborne-adventure",
  name: { en: "Windborne Adventure", zh_CN: "风旅冒险" },
  author: "Shinsekai",
  version: "1.0.0",
  tokens: {
    global: { fontFamily: "Georgia, serif", themeColor: "#f3cf57" },
    dialog: {
      background: "rgba(0,0,0,0.7)",
      borderColor: "#f3cf57",
      borderRadius: "8px",
      color: "#ffffff",
      heightPx: 166,
      padding: 20,
      textSizePx: 24,
      widthPct: 72,
    },
    input: { background: "#303744", color: "#ffffff", layout: "pill", maxWidthPx: 640 },
    name: { color: "#f3cf57", overlapPx: 12, textSizePx: 20 },
    options: { background: "#303744", color: "#ffffff", placement: "right", textSizePx: 18 },
    typewriter: { cps: 34 },
  },
};

const themeContext = vi.hoisted(() => ({
  activeId: "windborne-adventure" as string | null,
  loading: false,
  refresh: vi.fn(),
  removeTheme: vi.fn(),
  resolved: null,
  saveTheme: vi.fn(),
  style: {},
  switchTheme: vi.fn(),
  themes: [] as ChatThemeSummary[],
  uploadTheme: vi.fn(),
}));

const repository = vi.hoisted(() => ({
  getChatThemeManifest: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

vi.mock("../../../features/chat-stage/theme/ChatThemeProvider", () => ({
  chatThemeAssetUrl: (themeId: string, rel: string) => `/theme-assets/${themeId}/${rel}`,
  useOptionalChatTheme: () => themeContext,
}));

vi.mock("../../../entities/chat/repository", () => ({
  chatThemeQueryKey: ["chat", "themes"],
  getChatThemeManifest: repository.getChatThemeManifest,
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(configQueryKey, { system_config: { chat_ui_theme_id: "windborne-adventure" } });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <MemoryRouter initialEntries={["/settings/system/chat-themes/customize"]}>
            <Routes>
              <Route element={<ChatThemeCustomizerPage />} path="/settings/system/chat-themes/customize" />
              <Route element={<h1>Theme management destination</h1>} path="/settings/system/chat-themes" />
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

describe("ChatThemeCustomizerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    themeContext.activeId = "windborne-adventure";
    themeContext.loading = false;
    themeContext.themes = [
      {
        author: "Shinsekai",
        id: "windborne-adventure",
        name: { en: "Windborne Adventure", zh_CN: "风旅冒险" },
        source: "builtin",
        version: "1.0.0",
      },
    ];
    repository.getChatThemeManifest.mockImplementation(async (id: string) => ({
      ...structuredClone(baseManifest),
      id,
    }));
    themeContext.saveTheme.mockImplementation(async ({ manifest }: { manifest: ChatThemeManifest }) => ({
      id: manifest.id,
      name: manifest.name,
      source: "user" as const,
    }));
    themeContext.switchTheme.mockResolvedValue(undefined);
  });

  it("creates an editable copy of a built-in theme and updates the real preview style", async () => {
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "Chat UI 自定义" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("windborne-adventure-custom")).toBeInTheDocument();
    expect(screen.getByText("实时预览")).toBeInTheDocument();
    expect(
      screen.getByText("晚风穿过站台，远处城市的灯光正一盏盏亮起。今晚似乎会发生一些特别的事。"),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("主题色", { selector: "input.input" }), {
      target: { value: "#ff66aa" },
    });

    await waitFor(() => {
      const preview = container.querySelector<HTMLElement>(".chat-theme-customizer__preview-stage");
      expect(preview?.style.getPropertyValue("--chat-theme-color")).toBe("#ff66aa");
    });
  });

  it("saves, applies, and synchronizes the config cache", async () => {
    const { queryClient } = renderPage();
    await screen.findByDisplayValue("windborne-adventure-custom");

    fireEvent.change(screen.getByLabelText("主题色", { selector: "input.input" }), {
      target: { value: "#ff66aa" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    await waitFor(() =>
      expect(themeContext.saveTheme).toHaveBeenCalledWith(
        expect.objectContaining({
          baseId: "windborne-adventure",
          manifest: expect.objectContaining({
            id: "windborne-adventure-custom",
            tokens: expect.objectContaining({ global: expect.objectContaining({ themeColor: "#ff66aa" }) }),
          }),
        }),
      ),
    );
    expect(themeContext.switchTheme).toHaveBeenCalledWith("windborne-adventure-custom");
    expect(queryClient.getQueryData<{ system_config: { chat_ui_theme_id: string } }>(configQueryKey)).toEqual({
      system_config: { chat_ui_theme_id: "windborne-adventure-custom" },
    });
  });

  it("ignores an obsolete theme load and cannot save it under the newly selected source", async () => {
    const firstLoad = deferred<ChatThemeManifest>();
    const secondLoad = deferred<ChatThemeManifest>();
    themeContext.activeId = "theme-a";
    themeContext.themes = [
      { id: "theme-a", name: { en: "Theme A" }, source: "builtin" },
      { id: "theme-b", name: { en: "Theme B" }, source: "builtin" },
    ];
    repository.getChatThemeManifest.mockImplementation((id: string) =>
      id === "theme-a" ? firstLoad.promise : secondLoad.promise,
    );

    const { container } = renderPage();

    await waitFor(() => expect(repository.getChatThemeManifest).toHaveBeenCalledWith("theme-a"));
    const sourceSelect = container.querySelector<HTMLSelectElement>("select.custom-select__native");
    expect(sourceSelect).not.toBeNull();
    fireEvent.change(sourceSelect!, { target: { value: "theme-b" } });
    await waitFor(() => expect(repository.getChatThemeManifest).toHaveBeenCalledWith("theme-b"));

    await act(async () => {
      firstLoad.resolve({ ...structuredClone(baseManifest), id: "theme-a" });
      await Promise.resolve();
    });

    expect(screen.queryByDisplayValue("theme-a-custom")).not.toBeInTheDocument();
    const saveButton = container.querySelector<HTMLButtonElement>(
      ".chat-theme-customizer-page__actions .button--primary",
    );
    expect(saveButton).toBeDisabled();

    await act(async () => {
      secondLoad.resolve({ ...structuredClone(baseManifest), id: "theme-b" });
      await Promise.resolve();
    });
    await screen.findByDisplayValue("theme-b-custom");

    const colorInput = container.querySelector<HTMLInputElement>('input[type="color"]');
    expect(colorInput).not.toBeNull();
    fireEvent.change(colorInput!, { target: { value: "#33aaff" } });
    fireEvent.click(saveButton!);

    await waitFor(() =>
      expect(themeContext.saveTheme).toHaveBeenCalledWith(
        expect.objectContaining({
          baseId: "theme-b",
          manifest: expect.objectContaining({ id: "theme-b-custom" }),
        }),
      ),
    );
  });
});
