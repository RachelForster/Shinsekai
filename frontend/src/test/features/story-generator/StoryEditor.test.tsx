import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../../shared/i18n";
import type { StoryDocument } from "../../../shared/platform/storyEditorTypes";
import { StoryEditor } from "../../../features/story-generator/editor/StoryEditor";

const { readStoryDocument, saveStoryDocument, suggestStoryGraph } = vi.hoisted(() => ({
  readStoryDocument: vi.fn(),
  saveStoryDocument: vi.fn(),
  suggestStoryGraph: vi.fn(),
}));
vi.mock("../../../entities/story/repository", () => ({
  readStoryDocument,
  saveStoryDocument,
  suggestStoryGraph,
  storyLibraryQueryKey: ["story-library"],
}));
vi.mock("../../../features/story-generator/components/StoryLaunchButton", () => ({
  StoryLaunchButton: ({ storyPath, label }: { storyPath: string; label: string }) => (
    <button data-path={storyPath}>{label}</button>
  ),
}));

const document: StoryDocument = {
  storyPath: "stories/original.json",
  sourceHash: "original",
  title: "School mystery",
  version: 1,
  authoringBrief: "A mystery with a late reveal",
  graph: {
    startNodeId: "gate",
    nodes: [
      {
        id: "gate",
        title: "School gate",
        type: "limited_turn_node",
        instruction: "Invite the player inside.",
        maxRounds: 3,
        transitions: [{ to: "end", when: "Player agrees" }],
        defaultTo: "end",
      },
      { id: "end", title: "Truth", type: "ending_node" },
    ],
  },
};
const validation = { valid: true, issues: [] };
function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <StoryEditor storyPath={document.storyPath} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}
const text = () => screen.getByLabelText("Scene text / performance guidance");
const select = (label: string, option: string) => {
  fireEvent.click(screen.getByRole("combobox", { name: label }));
  fireEvent.click(screen.getByRole("option", { name: option }));
};

describe("story graph editor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    readStoryDocument.mockResolvedValue(structuredClone(document));
    saveStoryDocument.mockImplementation(async (input) => ({
      ...input,
      version: 2,
      sourceHash: "new",
      storyPath: "stories/edited.json",
      authoringBrief: document.authoringBrief,
    }));
  });

  it("edits selected nodes, saves a separate version and launches its new path", async () => {
    renderEditor();
    expect(await screen.findByDisplayValue(document.title)).toBeVisible();
    expect(screen.getByRole("button", { name: "Validate and save new version" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Ending Truth" }));
    fireEvent.change(text(), { target: { value: "The witness confesses." } });
    fireEvent.click(screen.getByRole("button", { name: "Validate and save new version" }));
    await waitFor(() => expect(saveStoryDocument).toHaveBeenCalledOnce());
    expect(saveStoryDocument.mock.calls[0][0]).toMatchObject({
      storyPath: document.storyPath,
      sourceHash: "original",
      graph: {
        nodes: [document.graph.nodes[0], { ...document.graph.nodes[1], instruction: "The witness confesses." }],
      },
    });
    expect(await screen.findByRole("button", { name: "Start playing the new version" })).toHaveAttribute(
      "data-path",
      "stories/edited.json",
    );
    expect(screen.getByRole("button", { name: "Validate and save new version" })).toBeDisabled();
  });

  it("adds nodes and connections, removes incoming edges on deletion, and supports undo", async () => {
    renderEditor();
    await screen.findByDisplayValue(document.title);
    fireEvent.click(screen.getByRole("button", { name: "Add node" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Node title" }), { target: { value: "Confrontation" } });
    fireEvent.change(text(), { target: { value: "Challenge the witness." } });
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    select("Target node", "Truth");
    fireEvent.change(screen.getByRole("textbox", { name: "Transition condition" }), {
      target: { value: "The truth emerges" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Turn-limited scene School gate/ }));
    select("Target node", "Confrontation");
    fireEvent.click(screen.getByRole("button", { name: "Validate and save new version" }));
    await waitFor(() => expect(saveStoryDocument).toHaveBeenCalledOnce());
    const graph = saveStoryDocument.mock.calls[0][0].graph;
    expect(graph.nodes).toHaveLength(3);
    expect(graph.nodes[0].defaultTo).toBe("node-1");
    expect(graph.nodes[2].transitions).toEqual([{ to: "end", when: "The truth emerges" }]);
    await screen.findByRole("button", { name: "Start playing the new version" });
    fireEvent.click(screen.getByRole("button", { name: /Free conversation Confrontation/ }));
    fireEvent.click(screen.getByRole("button", { name: "Delete node and its connections" }));
    expect(screen.queryByRole("button", { name: /Free conversation Confrontation/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Transition condition" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByRole("button", { name: /Free conversation Confrontation/ })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Transition condition" })).toHaveValue("Player agrees");
  });

  it("previews an LLM node change without applying or saving until accepted", async () => {
    const graph = structuredClone(document.graph);
    graph.nodes[0].instruction = "Invite the player cautiously.";
    let resolve!: (value: unknown) => void;
    suggestStoryGraph.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    renderEditor();
    await screen.findByDisplayValue(document.title);
    if (!screen.queryByRole("textbox", { name: "Revision request" }))
      fireEvent.click(screen.getAllByRole("button", { name: "Edit with an LLM" })[0]);
    fireEvent.change(screen.getByRole("textbox", { name: "Revision request" }), {
      target: { value: "Be more cautious" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate proposal" }));
    expect(text()).toBeDisabled();
    expect(suggestStoryGraph).toHaveBeenCalledWith(
      expect.objectContaining({ scope: "node", nodeId: "gate", instructions: "Be more cautious" }),
    );
    await act(async () => resolve({ graph, summary: "Adjusted the tone", validation }));
    expect(text()).toHaveValue("Invite the player inside.");
    const review = within(screen.getByRole("region", { name: "Review proposed changes" }));
    expect(review.getByText("Before")).toBeVisible();
    expect(review.getByText("After")).toBeVisible();
    expect(saveStoryDocument).not.toHaveBeenCalled();
    fireEvent.click(review.getByRole("button", { name: "Accept into draft" }));
    expect(text()).toHaveValue("Invite the player cautiously.");
    expect(saveStoryDocument).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(text()).toHaveValue("Invite the player inside.");
  });

  it("can ask the LLM to add nodes and alter the graph, then discard the candidate", async () => {
    const graph = structuredClone(document.graph);
    graph.nodes.push({ id: "new-ending", title: "Reconciliation", type: "ending_node" });
    graph.nodes[0].transitions?.push({ to: "new-ending", when: "Player forgives" });
    suggestStoryGraph.mockResolvedValue({ graph, summary: "New branch", validation });
    renderEditor();
    await screen.findByDisplayValue(document.title);
    fireEvent.click(screen.getAllByRole("button", { name: "Edit with an LLM" })[0]);
    select("Edit scope", "Whole graph (can generate new nodes)");
    if (!screen.queryByRole("textbox", { name: "Revision request" }))
      fireEvent.click(screen.getAllByRole("button", { name: "Edit with an LLM" })[0]);
    fireEvent.change(screen.getByRole("textbox", { name: "Revision request" }), {
      target: { value: "Add reconciliation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate proposal" }));
    expect(await screen.findByText("New branch")).toBeVisible();
    expect(suggestStoryGraph).toHaveBeenCalledWith(expect.objectContaining({ scope: "graph", nodeId: undefined }));
    fireEvent.click(screen.getByRole("button", { name: "Discard proposal" }));
    expect(screen.queryByText("Reconciliation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate and save new version" })).toBeDisabled();
  });

  it("keeps a draft after validation failure and after reopening the editor", async () => {
    saveStoryDocument.mockRejectedValue(new Error("Unreachable node"));
    const page = renderEditor();
    await screen.findByDisplayValue(document.title);
    fireEvent.change(text(), { target: { value: "My unsaved scene" } });
    fireEvent.click(screen.getByRole("button", { name: "Validate and save new version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unreachable node");
    expect(text()).toHaveValue("My unsaved scene");
    page.unmount();
    renderEditor();
    await screen.findByDisplayValue(document.title);
    expect(text()).toHaveValue("My unsaved scene");
  });

  it("keeps manual content on LLM failure and allows retry", async () => {
    suggestStoryGraph.mockRejectedValue(new Error("Model unavailable"));
    renderEditor();
    await screen.findByDisplayValue(document.title);
    fireEvent.change(text(), { target: { value: "My scene" } });
    if (!screen.queryByRole("textbox", { name: "Revision request" }))
      fireEvent.click(screen.getAllByRole("button", { name: "Edit with an LLM" })[0]);
    fireEvent.change(screen.getByRole("textbox", { name: "Revision request" }), { target: { value: "Revise" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate proposal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Model unavailable");
    expect(text()).toHaveValue("My scene");
    expect(screen.getByRole("button", { name: "Generate proposal" })).toBeEnabled();
  });
});
