import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../../app/shell/AppShell";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../app/shell/StartupUpdatePrompt", () => ({
  StartupUpdatePrompt: ({
    onStateChange,
  }: {
    onStateChange: (state: { checkComplete: boolean; open: boolean }) => void;
  }) => (
    <div data-testid="startup-update-prompt">
      <button onClick={() => onStateChange({ checkComplete: true, open: false })} type="button">
        Finish update check
      </button>
      <button onClick={() => onStateChange({ checkComplete: true, open: true })} type="button">
        Show update
      </button>
    </div>
  ),
}));

vi.mock("../../../features/release-highlights/FeatureHighlightsPrompt", () => ({
  FeatureHighlightsPrompt: ({ enabled }: { enabled: boolean }) => (
    <div data-enabled={enabled} data-testid="feature-highlights-prompt" />
  ),
}));

vi.mock("../../../features/tools/ToolsDrawer", () => ({
  ToolsDrawer: ({ onClose, open }: { onClose: () => void; open: boolean }) =>
    open ? (
      <aside aria-label="Tools drawer mock" role="dialog">
        <button onClick={onClose} type="button">
          Close drawer
        </button>
      </aside>
    ) : null,
}));

describe("AppShell", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: () => Promise.resolve({ stargazers_count: 3 }),
        ok: true,
      }),
    );
  });

  it("renders routed content and toggles the lazy tools drawer", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }} initialEntries={["/"]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<div>Workspace content</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </I18nProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Workspace content")).toBeInTheDocument();
    expect(screen.getByTestId("startup-update-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("feature-highlights-prompt")).toHaveAttribute("data-enabled", "false");
    fireEvent.click(screen.getByRole("button", { name: "Finish update check" }));
    expect(screen.getByTestId("feature-highlights-prompt")).toHaveAttribute("data-enabled", "true");
    fireEvent.click(screen.getByRole("button", { name: "Show update" }));
    expect(screen.getByTestId("feature-highlights-prompt")).toHaveAttribute("data-enabled", "false");
    fireEvent.click(screen.getByRole("button", { name: "Tools" }));

    expect(await screen.findByRole("dialog", { name: "Tools drawer mock" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close drawer" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Tools drawer mock" })).not.toBeInTheDocument());
  });
});
