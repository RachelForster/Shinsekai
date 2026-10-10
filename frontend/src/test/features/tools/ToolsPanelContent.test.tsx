import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolsPanelContent } from "../../../features/tools/ToolsPage";
import { SpriteGenerationPanel } from "../../../features/tools/SpriteGenerationPanel";
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

function renderPanel(content = <ToolsPanelContent />) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">{content}</I18nProvider>
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
    mockGenerateSpritePrompts.mockResolvedValue({ prompts: ["Keep face, hair and outfit: smile pose"] });
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Sprite tools" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Character" })).toHaveTextContent("Mika"));
    fireEvent.click(screen.getByRole("button", { name: "Generate prompt lines" }));

    await waitFor(() =>
      expect(mockGenerateSpritePrompts).toHaveBeenCalledWith(
        { characterName: "Mika", count: 1 },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    expect(screen.getByDisplayValue("Sprite 1: Keep face, hair and outfit: smile pose")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Reference image path"), {
      target: { value: "/tmp/reference.webp" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));

    await waitFor(() =>
      expect(mockGenerateSprites).toHaveBeenCalledWith(
        {
          autoLabel: true,
          characterName: "Mika",
          outputDir: undefined,
          prompts: ["Keep face, hair and outfit: smile pose"],
          provider: "configured",
          referenceImages: ["/tmp/reference.webp"],
        },
        expect.objectContaining({ onTaskUpdate: expect.any(Function) }),
      ),
    );
    expect(await screen.findByText("Sprite01.webp")).toBeInTheDocument();
  });

  it("regenerates only the chosen card using its original request and updates its tags", async () => {
    mockGenerateSprites
      .mockResolvedValueOnce({
        files: ["/tmp/sprites/wave.png", "/tmp/sprites/calm.png"],
        outputDir: "/tmp/sprites",
        message: "generated",
        labels: ["waving", "calm"],
      })
      .mockResolvedValueOnce({
        files: ["/tmp/sprites/new-wave.png"],
        outputDir: "/tmp/sprites",
        message: "generated",
        labels: ["smiling, waving"],
      });
    renderPanel();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Character" })).toHaveTextContent("Mika"));
    fireEvent.change(screen.getByPlaceholderText("Reference image path"), { target: { value: "/tmp/original.png" } });
    fireEvent.change(screen.getByPlaceholderText(/One prompt per line/), { target: { value: "wave\ncalm" } });
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));
    expect(await screen.findByLabelText("Tags for sprite 1")).toHaveValue("waving");
    fireEvent.change(screen.getByPlaceholderText("Reference image path"), { target: { value: "/tmp/other.png" } });
    fireEvent.change(screen.getByPlaceholderText(/One prompt per line/), { target: { value: "new unrelated prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Regenerate sprite 1" }));
    await waitFor(() =>
      expect(mockGenerateSprites).toHaveBeenLastCalledWith(
        {
          autoLabel: true,
          characterName: "Mika",
          outputDir: "/tmp/sprites",
          prompts: ["wave"],
          provider: "configured",
          referenceImages: ["/tmp/original.png"],
          seed: expect.any(Number),
        },
        expect.anything(),
      ),
    );
    expect(await screen.findByText("new-wave.png")).toBeInTheDocument();
    expect(screen.getByLabelText("Tags for sprite 1")).toHaveValue("smiling, waving");
    expect(screen.getByLabelText("Tags for sprite 2")).toHaveValue("calm");
    expect(screen.getByText("calm.png")).toBeInTheDocument();
    expect(screen.queryByText("wave.png")).not.toBeInTheDocument();
  });

  it("keeps existing cards after failed regeneration and allows retrying", async () => {
    mockGenerateSprites
      .mockResolvedValueOnce({ files: ["/tmp/sprites/wave.png"], outputDir: "/tmp/sprites", labels: ["waving"] })
      .mockRejectedValueOnce(new Error("Generator unavailable"));
    renderPanel();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Character" })).toHaveTextContent("Mika"));
    fireEvent.change(screen.getByPlaceholderText("Reference image path"), { target: { value: "/tmp/original.png" } });
    fireEvent.change(screen.getByPlaceholderText(/One prompt per line/), { target: { value: "wave" } });
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate sprite 1" }));
    expect(await screen.findByText("Generator unavailable")).toBeInTheDocument();
    expect(screen.getByText("wave.png")).toBeInTheDocument();
    expect(screen.getByLabelText("Tags for sprite 1")).toHaveValue("waving");
    expect(screen.getByRole("button", { name: "Regenerate sprite 1" })).toBeEnabled();
  });

  it("imports edited labels with their files and imports only the regenerated card afterwards", async () => {
    const onImport = vi.fn().mockResolvedValue(undefined);
    mockGenerateSprites
      .mockResolvedValueOnce({
        files: ["/tmp/wave.png", "/tmp/calm.png"],
        outputDir: "/tmp",
        labels: ["waving", "calm"],
      })
      .mockResolvedValueOnce({ files: ["/tmp/new-wave.png"], outputDir: "/tmp", labels: ["smiling, waving"] });
    renderPanel(
      <SpriteGenerationPanel
        fixedCharacterName="Mika"
        initialReferenceImages={["/tmp/original.png"]}
        onImportGenerated={onImport}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/One prompt per line/), { target: { value: "wave\ncalm" } });
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));
    fireEvent.change(await screen.findByLabelText("Tags for sprite 1"), { target: { value: "custom, waving" } });
    fireEvent.click(screen.getByRole("button", { name: "Add generated sprites to Mika" }));
    await waitFor(() =>
      expect(onImport).toHaveBeenCalledWith(["/tmp/wave.png", "/tmp/calm.png"], ["custom, waving", "calm"]),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Added to character sprites" })).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Regenerate sprite 1" }));
    expect(await screen.findByText("new-wave.png")).toBeInTheDocument();
    expect(screen.getByLabelText("Tags for sprite 2")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add generated sprites to Mika" }));
    await waitFor(() => expect(onImport).toHaveBeenLastCalledWith(["/tmp/new-wave.png"], ["smiling, waving"]));
    expect(onImport).toHaveBeenCalledTimes(2);
  });

  it("shows four cards with editable tags and keeps images when automatic labeling fails", async () => {
    mockGenerateSprites.mockResolvedValue({
      files: ["/tmp/a.png", "/tmp/b.png", "/tmp/c.png", "/tmp/d.png"],
      outputDir: "/tmp",
      labels: ["smiling", "", "calm", "waving"],
      labelErrors: [{ index: 1, message: "Configure vision first" }],
    });
    renderPanel();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Character" })).toHaveTextContent("Mika"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Automatically label generated sprites" }));
    fireEvent.change(screen.getByPlaceholderText("Reference image path"), { target: { value: "/tmp/original.png" } });
    fireEvent.change(screen.getByPlaceholderText(/One prompt per line/), {
      target: { value: "one\ntwo\nthree\nfour" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));
    expect(await screen.findByText("Configure vision first")).toBeInTheDocument();
    const gallery = screen.getByLabelText("Output previews");
    expect(within(gallery).getAllByRole("button", { name: /Regenerate sprite/ })).toHaveLength(4);
    fireEvent.change(screen.getByLabelText("Tags for sprite 2"), { target: { value: "serious, standing" } });
    expect(screen.getByLabelText("Tags for sprite 2")).toHaveValue("serious, standing");
    expect(screen.queryByText("Configure vision first")).not.toBeInTheDocument();
    expect(mockGenerateSprites).toHaveBeenCalledWith(expect.objectContaining({ autoLabel: false }), expect.anything());
  });

  it("sends reference images in order and allows removing a reference", async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Character" })).toHaveTextContent("Mika"));
    fireEvent.change(screen.getByPlaceholderText("Reference image path"), { target: { value: "/tmp/first.png" } });
    fireEvent.click(screen.getByRole("button", { name: "Add reference image" }));
    fireEvent.change(screen.getAllByPlaceholderText("Reference image path")[1], {
      target: { value: "/tmp/second.png" },
    });
    fireEvent.change(screen.getByPlaceholderText(/One prompt per line/), {
      target: { value: "保持原人物外观：右手挥手" },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "Image generation provider" }));
    fireEvent.click(screen.getByRole("option", { name: "Gemini" }));
    fireEvent.click(screen.getByRole("button", { name: "Batch-generate" }));
    await waitFor(() =>
      expect(mockGenerateSprites).toHaveBeenCalledWith(
        expect.objectContaining({
          prompts: ["保持原人物外观：右手挥手"],
          provider: "gemini",
          referenceImages: ["/tmp/first.png", "/tmp/second.png"],
        }),
        expect.anything(),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove reference image 1" }));
    expect(screen.getByPlaceholderText("Reference image path")).toHaveValue("/tmp/second.png");
  });
});
