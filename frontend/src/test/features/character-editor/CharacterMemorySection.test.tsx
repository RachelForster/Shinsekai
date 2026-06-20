import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterMemorySection } from "../../../features/character-editor/CharacterMemorySection";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderSection(overrides: Partial<Parameters<typeof CharacterMemorySection>[0]> = {}) {
  const props: Parameters<typeof CharacterMemorySection>[0] = {
    addPending: false,
    data: undefined,
    deletePending: false,
    depError: null,
    depInstalling: false,
    error: null,
    isError: false,
    isFetched: false,
    isFetching: false,
    isLoading: false,
    memoryInput: "",
    memoryName: "",
    onAddMemory: vi.fn(),
    onDeleteMemory: vi.fn(),
    onInstallDep: vi.fn(),
    onMemoryInputChange: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <CharacterMemorySection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("CharacterMemorySection", () => {
  it("keeps memory actions disabled until a character name and memory text are available", () => {
    renderSection({ memoryInput: "A remembered line" });

    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add memory" })).toBeDisabled();
  });

  it("renders memory rows and guards deletion for rows without ids", () => {
    const { props } = renderSection({
      data: {
        agentId: "agent-1",
        count: 2,
        memories: [
          { id: "mem-1", memory: "Likes the rooftop." },
          { id: "", memory: "Draft memory without an id." },
        ],
      },
      isFetched: true,
      memoryInput: "New memory",
      memoryName: "Mio",
    });

    expect(screen.getByText("Likes the rooftop.")).toBeInTheDocument();
    expect(screen.getByText("Draft memory without an id.")).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole("button", { name: "Delete" });
    fireEvent.click(deleteButtons[0]);
    expect(props.onDeleteMemory).toHaveBeenCalledWith({ id: "mem-1", memory: "Likes the rooftop." });
    expect(deleteButtons[1]).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Fresh memory" } });
    expect(props.onMemoryInputChange).toHaveBeenCalledWith("Fresh memory");

    fireEvent.click(screen.getByRole("button", { name: "Add memory" }));
    expect(props.onAddMemory).toHaveBeenCalledTimes(1);
  });
});
