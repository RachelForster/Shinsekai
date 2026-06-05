import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listCharacters } from "../entities/character/repository";
import { ToolsPage } from "../features/tools/ToolsPage";
import { I18nProvider } from "../shared/i18n/I18nProvider";
import { ErrorBoundary, QueryErrorState, ToastProvider } from "../shared/ui";

vi.mock("../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: vi.fn(),
}));

vi.mock("../entities/files/repository", () => ({
  fileUrl: (path: string) => path,
}));

const listCharactersMock = vi.mocked(listCharacters);

function renderWithProviders(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider language="en">
        <ToastProvider>{children}</ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("ErrorBoundary", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    consoleError.mockRestore();
  });

  it("renders a visible fallback for uncaught component errors", () => {
    function Broken(): ReactNode {
      throw new Error("render exploded");
    }

    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("界面发生错误");
    expect(screen.getByText("render exploded")).toBeInTheDocument();
  });
});

describe("QueryErrorState", () => {
  it("shows the error and retries through the supplied callback", () => {
    const retry = vi.fn();

    render(
      <QueryErrorState error={new Error("bridge offline")} onRetry={retry} retryLabel="Retry" title="Load failed" />,
    );

    expect(screen.getByText("Load failed")).toBeInTheDocument();
    expect(screen.getByText("bridge offline")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(retry).toHaveBeenCalledTimes(1);
  });
});

describe("ToolsPage query handling", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the feature page when character loading succeeds", async () => {
    listCharactersMock.mockResolvedValue([]);

    renderWithProviders(<ToolsPage />);

    expect(await screen.findByRole("heading", { name: "Tools" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sprite tools" })).toBeInTheDocument();
  });

  it("shows a retryable error instead of an empty character list when loading fails", async () => {
    listCharactersMock.mockRejectedValue(new Error("characters unavailable"));

    renderWithProviders(<ToolsPage />);

    expect(await screen.findByText("characters unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
