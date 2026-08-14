import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StoryGeneratorPage } from "../../../features/story-generator/StoryGeneratorPage";
import type { StoryGenerationTask } from "../../../entities/story/types";

const startStoryGeneration = vi.fn();
const resumeStoryGeneration = vi.fn();
const regenerateStoryGeneration = vi.fn();
const cancelStoryGeneration = vi.fn();

vi.mock("../../../entities/story/repository", () => ({
  startStoryGeneration: (...args: unknown[]) => startStoryGeneration(...args),
  resumeStoryGeneration: (...args: unknown[]) => resumeStoryGeneration(...args),
  regenerateStoryGeneration: (...args: unknown[]) => regenerateStoryGeneration(...args),
  cancelStoryGeneration: (...args: unknown[]) => cancelStoryGeneration(...args),
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

describe("StoryGeneratorPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("generates a draft and previews assumptions and validation", async () => {
    startStoryGeneration.mockResolvedValue(generatedTask());
    render(<StoryGeneratorPage />);

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
    render(<StoryGeneratorPage />);

    fireEvent.change(screen.getByRole("textbox", { name: "剧情梗概" }), { target: { value: "断点剧本" } });
    fireEvent.click(screen.getByRole("button", { name: "开始生成" }));
    fireEvent.click(await screen.findByRole("button", { name: "从断点继续" }));

    await waitFor(() => expect(resumeStoryGeneration).toHaveBeenCalledWith("generation-1", expect.anything()));
    expect(await screen.findByText("已通过确定性校验")).toBeInTheDocument();
  });
});
