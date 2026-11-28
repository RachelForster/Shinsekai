import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarNav } from "../../../app/shell/SidebarNav";
import { PluginStandalonePage } from "../../../features/plugin-manager/PluginStandalonePage";
import { I18nProvider } from "../../../shared/i18n";
import { toPageSectionDescriptors } from "../../../shared/plugin/PluginPageSections";
import { PluginSlot } from "../../../shared/plugin/PluginSlot";
import { PageSectionHost, ToastProvider } from "../../../shared/ui";
import type {
  PluginSectionContribution,
  PluginSidebarPageContribution,
  PluginSlotContribution,
  PluginUIDetail,
} from "../../../shared/platform/types";

const repoMocks = vi.hoisted(() => ({
  getPluginUiDetail: vi.fn<(id: string) => Promise<PluginUIDetail>>(),
  listPluginPageSections: vi.fn(),
  listPluginSidebarPages: vi.fn<() => Promise<PluginSidebarPageContribution[]>>(),
  listPluginSlotContributions: vi.fn<() => Promise<PluginSlotContribution[]>>(),
  runPluginSectionAction: vi.fn(),
  runPluginSlotContribution: vi.fn(),
  savePluginSectionValues: vi.fn(),
}));

vi.mock("../../../entities/plugin/repository", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../entities/plugin/repository")>();
  return {
    ...actual,
    getPluginUiDetail: (id: string) => repoMocks.getPluginUiDetail(id),
    listPluginPageSections: (query: unknown) => repoMocks.listPluginPageSections(query),
    listPluginSidebarPages: () => repoMocks.listPluginSidebarPages(),
    listPluginSlotContributions: () => repoMocks.listPluginSlotContributions(),
    runPluginSectionAction: (...args: unknown[]) => repoMocks.runPluginSectionAction(...args),
    runPluginSlotContribution: (...args: unknown[]) => repoMocks.runPluginSlotContribution(...args),
    savePluginSectionValues: (...args: unknown[]) => repoMocks.savePluginSectionValues(...args),
  };
});

vi.mock("../../../app/shell/useAppUpdateInfo", () => ({
  useAppUpdateInfo: () => ({ data: { version: "1.0.0" } }),
}));

describe("workspace plugin SDK UI extensions", () => {
  beforeEach(() => {
    repoMocks.listPluginSlotContributions.mockReset().mockResolvedValue([]);
    repoMocks.listPluginSidebarPages.mockReset().mockResolvedValue([]);
    repoMocks.listPluginPageSections.mockReset().mockResolvedValue([]);
    repoMocks.runPluginSlotContribution.mockReset();
    repoMocks.savePluginSectionValues.mockReset();
    repoMocks.runPluginSectionAction.mockReset();
    repoMocks.getPluginUiDetail.mockReset();
  });

  it("collapses overflow header buttons into an accessible menu, forwards context, and invalidates queries", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const makeAction = (id: string, order: number, enLabel: string): PluginSlotContribution => ({
      actionLabel: enLabel,
      actionType: "callback",
      actionable: true,
      description: "",
      i18n: { en: { label: enLabel, title: enLabel }, zh_CN: { label: `中文:${id}`, title: `中文:${id}` } },
      icon: "wand",
      id,
      order,
      pageId: "",
      pluginId: "demo",
      pluginVersion: "1.0.0",
      presentation: "button",
      slot: "character-header-actions",
      title: enLabel,
      variant: "ghost",
    });

    repoMocks.listPluginSlotContributions.mockResolvedValue([
      makeAction("first", 1, "First"),
      makeAction("second", 2, "Second"),
      makeAction("third", 3, "Third"),
    ]);
    repoMocks.runPluginSlotContribution.mockResolvedValue({
      i18nMessage: { en: "Synced English", zh_CN: "同步完成" },
      id: "third",
      kind: "success",
      message: "fallback",
      pluginId: "demo",
      refresh: ["characters"],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <I18nProvider language="en">
            <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
              <PluginSlot
                context={{ entityId: "Alice", entityType: "character", page: "character" }}
                maxInline={2}
                slot="character-header-actions"
              />
            </MemoryRouter>
          </I18nProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("button", { name: "First" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Second" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Third" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More plugin actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Third" }));

    await waitFor(() =>
      expect(repoMocks.runPluginSlotContribution).toHaveBeenCalledWith("demo", "third", {
        entityId: "Alice",
        entityType: "character",
        locale: "en",
        page: "character",
      }),
    );
    expect(await screen.findByText("Synced English")).toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["characters"] });
  });

  it("navigates to /settings/plugins/:pluginId/:pageId when open-plugin-page runs with a router", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    repoMocks.listPluginSlotContributions.mockResolvedValue([
      {
        actionLabel: "Open Board",
        actionType: "open-plugin-page",
        actionable: true,
        description: "",
        icon: "gamepad",
        id: "open-board",
        order: 1,
        pageId: "lobby",
        pageMode: "navigate",
        pluginId: "demo.game",
        pluginVersion: "1.0.0",
        presentation: "button",
        slot: "app-topbar-actions",
        title: "Open Board",
        variant: "ghost",
      },
    ]);
    repoMocks.getPluginUiDetail.mockResolvedValue({
      pages: [
        {
          frontendUrl: "/api/plugins/demo.game/frontend/lobby/",
          id: "lobby",
          kind: "settings",
          navLabel: "Werewolf Lobby",
          order: 1,
          pluginId: "demo.game",
          pluginVersion: "1.0.0",
          title: "Werewolf Lobby",
        },
      ],
      plugin: {
        author: "Dev",
        description: "Game",
        enabled: true,
        entry: "demo.game",
        id: "demo.game",
        loaded: true,
        permissions: [],
        settingsPages: [],
        slots: [],
        title: "Werewolf",
        toolsTabs: [],
        version: "1.0.0",
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <I18nProvider language="en">
            <MemoryRouter
              future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
              initialEntries={["/settings"]}
            >
              <Routes>
                <Route element={<PluginSlot context={{ page: "app" }} slot="app-topbar-actions" />} path="/settings" />
                <Route element={<PluginStandalonePage />} path="/settings/plugins/:pluginId/:pageId" />
              </Routes>
            </MemoryRouter>
          </I18nProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Open Board" }));
    expect(await screen.findByRole("heading", { name: "Werewolf Lobby" })).toBeInTheDocument();
    expect(screen.getByTitle("Werewolf Lobby").tagName).toBe("IFRAME");
  });

  it("renders sidebar plugin pages and splits schema/iframe sections into 2-column slots", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ stargazers_count: 1 }),
        ok: true,
      }),
    );

    repoMocks.listPluginSidebarPages.mockResolvedValue([
      {
        description: "Play board",
        frontendUrl: "/api/plugins/werewolf/frontend/board/",
        i18n: { en: { navLabel: "Werewolf Arena", title: "Werewolf Arena" } },
        navIcon: "gamepad",
        navLabel: "狼人杀",
        order: 1,
        pageId: "board",
        pluginId: "werewolf",
        pluginVersion: "1.0.0",
        title: "Werewolf",
      },
    ]);

    const rawSections: PluginSectionContribution[] = [
      {
        actions: [{ confirm: "Reset rules?", id: "reset", label: "Reset", order: 1, variant: "ghost" }],
        canSave: true,
        description: "Template rules",
        id: "roles",
        navLabel: "Roles",
        order: 10,
        page: "template",
        pluginId: "werewolf",
        pluginVersion: "1.0.0",
        renderer: "schema",
        schema: [{ fields: [{ key: "wolves", label: "Wolves", type: "integer" }], id: "g", title: "Counts" }],
        slot: "sidebar",
        title: "Role Counts",
        values: { wolves: 3 },
      },
      {
        description: "Live stage preview",
        frontendUrl: "/api/plugins/werewolf/frontend/preview/",
        id: "board-embed",
        maxHeight: 600,
        minHeight: 180,
        navLabel: "Board Embed",
        order: 20,
        page: "template",
        pageId: "preview",
        pluginId: "werewolf",
        pluginVersion: "1.0.0",
        renderer: "iframe",
        slot: "main",
        title: "Stage Preview",
      },
    ];
    repoMocks.savePluginSectionValues.mockResolvedValue({
      kind: "success",
      message: "Rules updated",
      refresh: ["templates"],
      section: rawSections[0],
    });
    repoMocks.runPluginSectionAction.mockResolvedValue({
      kind: "info",
      message: "Rules reset",
      result: {},
      section: rawSections[0],
    });

    const descriptors = toPageSectionDescriptors(rawSections, {
      context: { entityId: "tpl-1", entityType: "template", page: "template" },
      defaultSlot: "main",
      preserveDeclaredSlot: true,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <I18nProvider language="en">
            <MemoryRouter
              future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
              initialEntries={["/settings/templates"]}
            >
              <SidebarNav assistantOpen={false} onAssistantToggle={vi.fn()} />
              <div data-testid="main-col">
                <PageSectionHost ctx={{}} sections={descriptors} slot="main" />
              </div>
              <div data-testid="sidebar-col">
                <PageSectionHost ctx={{}} sections={descriptors} slot="sidebar" />
              </div>
            </MemoryRouter>
          </I18nProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );

    const navLink = await screen.findByRole("link", { name: "Werewolf Arena" });
    expect(navLink).toHaveAttribute("href", "/settings/plugins/werewolf/board");

    expect(screen.getByTitle("Stage Preview").closest("[data-testid='main-col']")).not.toBeNull();
    expect(screen.getByText("Role Counts").closest("[data-testid='sidebar-col']")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Save section" }));
    await waitFor(() => expect(repoMocks.savePluginSectionValues).toHaveBeenCalled());
    expect(await screen.findByText("Rules updated")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(repoMocks.runPluginSectionAction).toHaveBeenCalled());
    expect(await screen.findByText("Rules reset")).toBeInTheDocument();

    vi.unstubAllGlobals();
  });
});
