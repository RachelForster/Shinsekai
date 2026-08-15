import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StoryEditorPage } from "../../../features/story-editor/StoryEditorPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const getStoryProject = vi.fn();
const getStoryProjectGraph = vi.fn();
const patchStoryProject = vi.fn();
const previewStoryCast = vi.fn();
const previewStoryPath = vi.fn();
const proposeStoryAiPatch = vi.fn();
const publishStoryProject = vi.fn();
const undoStoryProject = vi.fn();
const validateStoryProject = vi.fn();

vi.mock("../../../entities/story/repository", () => ({
  getStoryProject: (...args: unknown[]) => getStoryProject(...args),
  getStoryProjectGraph: (...args: unknown[]) => getStoryProjectGraph(...args),
  patchStoryProject: (...args: unknown[]) => patchStoryProject(...args),
  previewStoryCast: (...args: unknown[]) => previewStoryCast(...args),
  previewStoryPath: (...args: unknown[]) => previewStoryPath(...args),
  proposeStoryAiPatch: (...args: unknown[]) => proposeStoryAiPatch(...args),
  publishStoryProject: (...args: unknown[]) => publishStoryProject(...args),
  undoStoryProject: (...args: unknown[]) => undoStoryProject(...args),
  validateStoryProject: (...args: unknown[]) => validateStoryProject(...args),
}));

const document = {
  manifest: {
    createdAt: 1,
    draftRevision: 3,
    id: "campus-mystery",
    publishedSourceHash: "",
    publishedVersion: 1,
    title: "校园谜案",
    updatedAt: 2,
  },
  resources: { bindings: {}, characters: [] },
  source: {
    id: "campus-mystery",
    variables: { "trust.ling": { initial: 0, type: "integer" } },
    semanticSignals: [],
    cast: {
      characters: [
        { id: "ling", roles: ["companion"], source: { type: "embedded", path: "ling.yaml" }, tags: ["student"] },
      ],
      initialCast: ["ling"],
    },
    narrativeGraph: {
      startNodeId: "opening",
      nodes: [
        {
          id: "opening",
          title: "开场",
          type: "story",
          commitment: "draft",
          onEnter: [],
          choices: [],
          castPolicy: { mode: "fixed", required: ["ling"], constraints: { maxActive: 2 } },
        },
      ],
    },
    logicGraph: { version: 1, nodes: [], edges: [] },
  },
  validation: {
    castFailureNodeIds: [],
    endingCoverage: 1,
    endingNodeIds: [],
    exploredStates: 2,
    issues: [],
    reachableEndingIds: [],
    reachableNodeIds: ["opening"],
    sourceHash: "hash",
    valid: true,
  },
};

const graph = {
  diagnostics: [],
  narrative: { edges: [], nodes: [{ id: "opening", title: "开场", type: "story", x: 0, y: 0 }] },
  rules: { edges: [], nodes: [] },
  sourceMap: { "node:opening": "$.narrativeGraph.nodes[0]" },
};

function renderPage() {
  return render(
    <I18nProvider language="zh_CN">
      <MemoryRouter initialEntries={["/settings/stories/campus-mystery/edit"]}>
        <Routes>
          <Route element={<StoryEditorPage />} path="/settings/stories/:storyId/edit" />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("StoryEditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getStoryProject.mockResolvedValue(document);
    getStoryProjectGraph.mockResolvedValue(graph);
    patchStoryProject.mockResolvedValue({
      baseRevision: 3,
      candidateRevision: 4,
      committed: true,
      diff: [],
      document,
      source: document.source,
      validation: document.validation,
    });
    previewStoryCast.mockResolvedValue({
      activeCharacterIds: ["ling"],
      candidates: [{ accepted: true, characterId: "ling", reasonCode: "selected" }],
      error: null,
      nodeId: "opening",
      roleBindings: {},
      unresolvedRoles: [],
      valid: true,
    });
  });

  it("renders structured editors and graph diagnostics", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "校园谜案" })).toBeInTheDocument();
    expect(screen.queryByLabelText("选项 1 文案")).not.toBeInTheDocument();
    expect(screen.getByText("变量、语义信号与规则")).toBeInTheDocument();
    expect(screen.getByText("node:opening")).toBeInTheDocument();
  });

  it("adds a node through a versioned structured patch", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "校园谜案" });
    fireEvent.click(screen.getByRole("button", { name: "+ 节点" }));
    await waitFor(() => expect(patchStoryProject).toHaveBeenCalled());
    expect(patchStoryProject.mock.calls[0][0]).toMatchObject({ baseRevision: 3, commit: true });
    expect(patchStoryProject.mock.calls[0][0].patch.operations[0]).toMatchObject({
      op: "add",
      path: "/narrativeGraph/nodes/-",
    });
  });

  it("inspects deterministic cast candidates for the selected scene", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "校园谜案" });
    fireEvent.click(screen.getByRole("button", { name: "预览演员表" }));
    await waitFor(() => expect(previewStoryCast).toHaveBeenCalledWith({ id: "campus-mystery", nodeId: "opening" }));
    expect(await screen.findByText("已选：ling")).toBeInTheDocument();
  });

  it("initializes a missing onEnter array before appending an effect", async () => {
    const nodeWithoutEnter = { ...document.source.narrativeGraph.nodes[0] };
    delete (nodeWithoutEnter as { onEnter?: unknown }).onEnter;
    const source = {
      ...document.source,
      narrativeGraph: {
        ...document.source.narrativeGraph,
        nodes: [nodeWithoutEnter],
      },
    };
    getStoryProject.mockResolvedValue({ ...document, source });
    renderPage();
    await screen.findByRole("heading", { name: "校园谜案" });
    fireEvent.change(screen.getByPlaceholderText("变量 ID"), { target: { value: "trust.ling" } });
    fireEvent.click(screen.getByRole("button", { name: "添加增量" }));
    await waitFor(() => expect(patchStoryProject).toHaveBeenCalled());
    expect(patchStoryProject.mock.calls[0][0].patch.operations).toEqual([
      { op: "add", path: "/narrativeGraph/nodes/0/onEnter", value: [] },
      {
        op: "add",
        path: "/narrativeGraph/nodes/0/onEnter/-",
        value: { increment: ["trust.ling", 1] },
      },
    ]);
  });

  it("does not reuse a remaining variable id after deletion", async () => {
    getStoryProject.mockResolvedValue({
      ...document,
      source: {
        ...document.source,
        variables: { "state.variable_2": { initial: 0, type: "integer" } },
      },
    });
    renderPage();
    await screen.findByRole("heading", { name: "校园谜案" });
    fireEvent.click(screen.getByRole("button", { name: "+ 变量" }));
    await waitFor(() => expect(patchStoryProject).toHaveBeenCalled());
    expect(patchStoryProject.mock.calls[0][0].patch.operations[0]).toMatchObject({
      op: "add",
      path: "/variables/state.variable_1",
    });
  });
});
