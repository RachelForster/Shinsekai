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
const repairStoryProject = vi.fn();
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
  repairStoryProject: (...args: unknown[]) => repairStoryProject(...args),
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
  narrative: {
    edges: [{ from: "opening", id: "choice:opening/next", label: "继续", to: "ending" }],
    nodes: [
      { id: "opening", title: "开场", type: "story", x: 0, y: 0 },
      { id: "ending", title: "结局", type: "ending", x: 300, y: 0 },
    ],
  },
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
    repairStoryProject.mockResolvedValue({
      ...document,
      manifest: { ...document.manifest, draftRevision: 4 },
      validation: { ...document.validation, issues: [], valid: true },
    });
  });

  it("renders structured editors and graph diagnostics", async () => {
    const { container } = renderPage();
    expect(await screen.findByRole("heading", { name: "校园谜案" })).toBeInTheDocument();
    expect(screen.queryByLabelText("选项 1 文案")).not.toBeInTheDocument();
    expect(screen.getByText("变量、语义信号与规则")).toBeInTheDocument();
    expect(screen.getByText("node:opening")).toBeInTheDocument();
    expect(screen.getByLabelText("图关系")).toBeInTheDocument();
    expect(container.querySelector(".story-editor-graph-lines path")).not.toBeNull();
  });

  it("shows an actionable fix for graph compilation errors", async () => {
    getStoryProject.mockResolvedValue({
      ...document,
      validation: {
        ...document.validation,
        valid: false,
        issues: [
          {
            code: "rule.missing_port",
            message: "destination port 'input-x' does not exist",
            path: "$.logicGraph.edges[0].to.port",
            severity: "error",
            suggestion: "Use an input port declared by the destination rule node type.",
          },
        ],
      },
    });

    renderPage();

    expect(await screen.findByText("rule.missing_port")).toBeInTheDocument();
    expect(screen.getByText(/修改建议：Use an input port declared/)).toBeInTheDocument();
  });

  it("repairs the complete invalid draft with one click", async () => {
    getStoryProject.mockResolvedValue({
      ...document,
      validation: {
        ...document.validation,
        valid: false,
        issues: [
          {
            code: "semantic.target_disabled",
            message: "target variable does not allow semantic input",
            path: "$.semanticSignals[0].effectsByStrength.strong[0]",
            severity: "error",
            suggestion: "Enable allowSemanticInput on the target integer variable.",
          },
        ],
      },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "一键 Repair" }));

    await waitFor(() =>
      expect(repairStoryProject).toHaveBeenCalledWith({
        id: "campus-mystery",
        baseRevision: 3,
      }),
    );
    expect(await screen.findByText("Repair 完成，草稿已重新校验并保存。")).toBeInTheDocument();
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

  it("adds a compiler-supported rule node type", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "校园谜案" });

    fireEvent.click(screen.getByRole("button", { name: "+ 规则节点" }));

    await waitFor(() => expect(patchStoryProject).toHaveBeenCalled());
    expect(patchStoryProject.mock.calls[0][0].patch.operations[0]).toMatchObject({
      op: "add",
      path: "/logicGraph/nodes/-",
      value: { id: "rule-1", type: "cast-resolve", config: {} },
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

  it("updates the node inspector when another scene is selected from the list or graph", async () => {
    const endingNode = {
      id: "ending",
      title: "结局",
      type: "ending",
      commitment: "frozen",
      enterWhen: { gte: ["trust.ling", 10] },
      onEnter: [],
      choices: [{ id: "stay", label: "留下", goto: "opening" }],
      castPolicy: { mode: "fixed", required: [], constraints: { maxActive: 1 } },
    };
    getStoryProject.mockResolvedValue({
      ...document,
      source: {
        ...document.source,
        narrativeGraph: {
          ...document.source.narrativeGraph,
          nodes: [...document.source.narrativeGraph.nodes, endingNode],
        },
      },
    });
    const { container } = renderPage();
    await screen.findByRole("heading", { name: "校园谜案" });
    expect(screen.getByLabelText("标题")).toHaveValue("开场");

    fireEvent.click(screen.getByRole("navigation", { name: "剧情节点" }).querySelector("button:nth-child(2)")!);
    expect(screen.getByLabelText("标题")).toHaveValue("结局");
    expect(screen.getByLabelText("节点类型")).toHaveValue("ending");
    expect(screen.getByPlaceholderText("例如 trust.ling >= 10")).toHaveValue("trust.ling >= 10");
    expect(screen.getByLabelText("选项 1 文案")).toHaveValue("留下");

    fireEvent.click(container.querySelector('.story-editor-graph-node[data-node-id="opening"]')!);
    expect(screen.getByLabelText("标题")).toHaveValue("开场");
    expect(screen.getByLabelText("节点类型")).toHaveValue("story");
    expect(screen.queryByLabelText("选项 1 文案")).not.toBeInTheDocument();
  });
});
