import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolsPanelContent } from "../../../features/tools/ToolsPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockListCharacters = vi.fn();
const mockGenerateSpritePrompts = vi.fn();
const mockGenerateSprites = vi.fn();
const mockCropSprites = vi.fn();
const mockRemoveSpriteBackground = vi.fn();

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => mockListCharacters(),
}));

vi.mock("../../../entities/tools/repository", () => ({
  cropSprites: (input: unknown, options: unknown) => mockCropSprites(input, options),
  generateSpritePrompts: (input: unknown, options: unknown) => mockGenerateSpritePrompts(input, options),
  generateSprites: (input: unknown, options: unknown) => mockGenerateSprites(input, options),
  removeSpriteBackground: (input: unknown, options: unknown) => mockRemoveSpriteBackground(input, options),
}));

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <ToolsPanelContent />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ToolsPanelContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListCharacters.mockResolvedValue([{ color: "#66ccff", name: "Mika" }]);
    mockGenerateSpritePrompts.mockResolvedValue({ prompts: ["smile pose"] });
    mockGenerateSprites.mockResolvedValue({
      files: ["/tmp/sprites/Sprite01.webp"],
      message: "generated",
      outputDir: "/tmp/sprites",
    });
    mockCropSprites.mockResolvedValue({ message: "cropped" });
    mockRemoveSpriteBackground.mockResolvedValue({ message: "removed" });
  });

  it("generates prompt lines and sends extracted prompts to sprite generation", async () => {
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Sprite tools" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("Mika"));
    fireEvent.click(screen.getByRole("button", { name: "Generate prompt lines" }));

    await waitFor(() =>
      expect(mockGenerateSpritePrompts).toHaveBeenCalledWith(
        { characterName: "Mika", count: 1 },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    expect(screen.getByDisplayValue("Sprite 1: smile pose")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Reference image path"), {
      target: { value: "/tmp/reference.webp" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));

    await waitFor(() =>
      expect(mockGenerateSprites).toHaveBeenCalledWith(
        {
          characterName: "Mika",
          outputDir: undefined,
          prompts: ["smile pose"],
          referenceImage: "/tmp/reference.webp",
        },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    expect(await screen.findByText("Sprite01.webp")).toBeInTheDocument();
  });
});
