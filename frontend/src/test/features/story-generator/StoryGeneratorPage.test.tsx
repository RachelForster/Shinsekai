import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StoryGeneratorPage } from "../../../features/story-generator/StoryGeneratorPage";
import type { StoryGenerationTask } from "../../../entities/story/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const startStoryGeneration = vi.fn();
const resumeStoryGeneration = vi.fn();
const regenerateStoryGeneration = vi.fn();
const cancelStoryGeneration = vi.fn();
const importGeneratedStoryProject = vi.fn();
const listCharacters = vi.fn();

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => listCharacters(),
}));

vi.mock("../../../entities/story/repository", () => ({
  startStoryGeneration: (...args: unknown[]) => startStoryGeneration(...args),
  resumeStoryGeneration: (...args: unknown[]) => resumeStoryGeneration(...args),
  regenerateStoryGeneration: (...args: unknown[]) => regenerateStoryGeneration(...args),
  cancelStoryGeneration: (...args: unknown[]) => cancelStoryGeneration(...args),
  importGeneratedStoryProject: (...args: unknown[]) => importGeneratedStoryProject(...args),
}));

function generatedTask(status: StoryGenerationTask["status"] = "succeeded"): StoryGenerationTask {
  return {
    artifactHashes: {},
    assumptions: ["以三幕结构展开"],
    cancelRequested: false,
    completedStages: ["requirements", "bible", "characters", "state", "narrative", "logic", "resources"],
    cost: { estimatedTokens: 1200, inputChars: 2400, outputChars: 1200, requests: 7 },
    createdAt: 1,
    currentStage: status === "succeeded" ? "complete" : "narrative",
    draftPath: status === "succeeded" ? "draft.json" : "",
    error: null,
    id: "generation-1",
    options: {},
    repairAttempts: 0,
    resourceCatalog: {},
    status,
    synopsis: "校园谜案",
    updatedAt: 2,
    validation: {
      castFailureNodeIds: [],
      endingCoverage: 1,
      endingNodeIds: ["truth"],
      exploredStates: 18,
      issues: [],
      reachableEndingIds: ["truth"],
      reachableNodeIds: ["start", "truth"],
      sourceHash: "sha256",
      valid: true,
    },
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return render(
    <I18nProvider language="zh_CN">
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <StoryGeneratorPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

describe("StoryGeneratorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listCharacters.mockResolvedValue([{ color: "#66ccff", name: "Nanami" }]);
  });

  it("mentions a system character from the synopsis editor", async () => {
    renderPage();
    const synopsis = await screen.findByRole("textbox", { name: "剧情梗概" });
    fireEvent.change(synopsis, { target: { value: "@" } });
    expect(await screen.findByRole("option", { name: "用户" })).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("option", { name: "Nanami" }));
    expect(synopsis).toHaveValue("@Nanami ");
  });

  it("generates a draft and previews assumptions and validation", async () => {
    startStoryGeneration.mockResolvedValue(generatedTask());
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "剧情梗概" }), { target: { value: "调查废弃校舍" } });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));

    await waitFor(() => expect(startStoryGeneration).toHaveBeenCalled());
    expect(await screen.findByText("以三幕结构展开")).toBeInTheDocument();
    expect(screen.getByText("已通过确定性校验")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("resumes a failed task from its checkpoint", async () => {
    startStoryGeneration.mockResolvedValue(generatedTask("failed"));
    resumeStoryGeneration.mockResolvedValue(generatedTask());
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "剧情梗概" }), { target: { value: "断点剧本" } });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));
    fireEvent.click(await screen.findByRole("button", { name: "从断点继续" }));

    await waitFor(() => expect(resumeStoryGeneration).toHaveBeenCalledWith("generation-1", expect.anything()));
    expect(await screen.findByText("已通过确定性校验")).toBeInTheDocument();
  });

  it("automatically continues a failed generation from its checkpoint", async () => {
    startStoryGeneration.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        error: "transient",
        generationTask: generatedTask("failed"),
        id: "bridge-1",
        kind: "story-generation",
        logs: [],
        message: "transient",
        phase: "failed",
        status: "failed",
        title: "AI story compiler",
        updatedAt: 2,
      });
      throw new Error("transient");
    });
    resumeStoryGeneration.mockResolvedValue(generatedTask());
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "剧情梗概" }), { target: { value: "调查废弃校舍" } });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));

    await waitFor(() => expect(resumeStoryGeneration).toHaveBeenCalledWith("generation-1", expect.anything()));
    expect(await screen.findByText("已通过确定性校验")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lets the user open a failed generation draft", async () => {
    const failed = generatedTask("failed");
    failed.draftPath = "draft.json";
    failed.currentStage = "repair";
    failed.repairAttempts = 3;
    failed.error = {
      code: "generation.validation_failed",
      message: "generated story did not pass validation after bounded repair",
    };
    failed.validation = {
      ...failed.validation!,
      valid: false,
      issues: [
        {
          code: "simulation.no_ending",
          message: "story must define at least one ending",
          path: "/narrativeGraph",
          severity: "error",
          suggestion: "Add a reachable ending node.",
        },
      ],
    };
    startStoryGeneration.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        error: failed.error?.message,
        generationTask: failed,
        id: "bridge-1",
        kind: "story-generation",
        logs: [],
        message: failed.error?.message ?? "",
        phase: "failed",
        status: "failed",
        title: "AI story compiler",
        updatedAt: 2,
      });
      throw new Error(failed.error?.message);
    });
    resumeStoryGeneration.mockImplementation(async (_id, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        error: failed.error?.message,
        generationTask: failed,
        id: "bridge-1",
        kind: "story-generation",
        logs: [],
        message: failed.error?.message ?? "",
        phase: "failed",
        status: "failed",
        title: "AI story compiler",
        updatedAt: 2,
      });
      throw new Error(failed.error?.message);
    });
    importGeneratedStoryProject.mockResolvedValue({
      manifest: { id: "campus-mystery" },
    });
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "剧情梗概" }), { target: { value: "调查废弃校舍" } });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("生成结果在有限次自动修补后仍未通过校验");
    expect(screen.getByText("/narrativeGraph")).toBeInTheDocument();
    expect(screen.getByText("修改建议：Add a reachable ending node.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "打开编辑器" }));
    await waitFor(() => expect(importGeneratedStoryProject).toHaveBeenCalledWith("generation-1"));
  });
});
