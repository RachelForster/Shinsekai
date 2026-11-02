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
    isChecking: false,
    isError: false,
    isFetched: false,
    isFetching: false,
    isLoading: false,
    memoryInput: "",
    memoryImportPending: false,
    memoryName: "",
    memoryPage: 1,
    memoryTotalPages: 1,
    activeSearchQuery: "",
    onAddMemory: vi.fn(),
    onClearSearch: vi.fn(),
    onDeleteMemory: vi.fn(),
    onInstallDep: vi.fn(),
    onImportMemories: vi.fn(),
    onMemoryInputChange: vi.fn(),
    onMemoryPageChange: vi.fn(),
    onRefresh: vi.fn(),
    onSearch: vi.fn(),
    onSearchInputChange: vi.fn(),
    searchInput: "",
    searchPending: false,
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
    expect(screen.getByRole("button", { name: "Import from files" })).toBeDisabled();
    screen.getAllByRole("textbox").forEach((textbox) => expect(textbox).toBeDisabled());
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

    fireEvent.change(screen.getByPlaceholderText("Memory content"), { target: { value: "Fresh memory" } });
    expect(props.onMemoryInputChange).toHaveBeenCalledWith("Fresh memory");

    fireEvent.click(screen.getByRole("button", { name: "Add memory" }));
    expect(props.onAddMemory).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Import from files" }));
    expect(props.onImportMemories).toHaveBeenCalledTimes(1);
  });

  it("submits memory search and pages through results", () => {
    const onSearch = vi.fn();
    const onSearchInputChange = vi.fn();
    const onMemoryPageChange = vi.fn();
    const onClearSearch = vi.fn();

    renderSection({
      activeSearchQuery: "tea",
      data: {
        agentId: "agent-1",
        count: 9,
        memories: [{ id: "mem-9", memory: "Likes jasmine tea." }],
      },
      isFetched: true,
      memoryName: "Mio",
      memoryPage: 2,
      memoryTotalPages: 2,
      onClearSearch,
      onMemoryPageChange,
      onSearch,
      onSearchInputChange,
      searchInput: "tea",
    });

    fireEvent.change(screen.getByPlaceholderText("Search related memories"), { target: { value: "coffee" } });
    expect(onSearchInputChange).toHaveBeenCalledWith("coffee");

    fireEvent.keyDown(screen.getByPlaceholderText("Search related memories"), { key: "Enter" });
    expect(onSearch).toHaveBeenCalledTimes(1);

    expect(screen.getByText('9 results for "tea"')).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Previous page"));
    expect(onMemoryPageChange).toHaveBeenCalledWith(expect.any(Function));

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onClearSearch).toHaveBeenCalledTimes(1);
  });

  it("shows dependency install UI when depError is set", () => {
    const onInstall = vi.fn();

    renderSection({
      depError: { kind: "missing_dependency", moduleName: "mem0", packageName: "mem0ai" },
      memoryName: "Mio",
      onInstallDep: onInstall,
    });

    // Install button is present (not "Add memory" which should be hidden)
    expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add memory" })).not.toBeInTheDocument();
    expect(screen.getByText("Missing Python dependency")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    expect(onInstall).toHaveBeenCalledTimes(1);
  });

  it("shows installing state and disables refresh when depInstalling is true", () => {
    renderSection({
      depError: { kind: "missing_dependency", moduleName: "mem0", packageName: "mem0ai" },
      depInstalling: true,
      memoryName: "Mio",
    });

    expect(screen.getByRole("button", { name: "Installing mem0ai…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Installing mem0ai…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  });

  it("shows checking state with initializing text when isChecking is true", () => {
    renderSection({
      isChecking: true,
      memoryName: "Mio",
    });

    expect(screen.getByRole("button", { name: "Initializing memory system…" })).toBeDisabled();
    // Button label + EmptyState title both show the text
    expect(screen.getAllByText("Initializing memory system…")).toHaveLength(2);
  });
});
