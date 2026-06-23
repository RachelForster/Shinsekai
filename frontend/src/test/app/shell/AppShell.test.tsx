import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../../app/shell/AppShell";
import { I18nProvider } from "../../../shared/i18n";

vi.mock("../../../app/shell/StartupUpdatePrompt", () => ({
  StartupUpdatePrompt: () => <div data-testid="startup-update-prompt" />,
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
    fireEvent.click(screen.getByRole("button", { name: "Tools" }));

    expect(await screen.findByRole("dialog", { name: "Tools drawer mock" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close drawer" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Tools drawer mock" })).not.toBeInTheDocument());
  });
});
