import { getPlatform } from "../../shared/platform/platform";
import type {
  StoryAiPatchProposal,
  StoryCastPreview,
  StoryGenerationInput,
  StoryGenerationStage,
  StoryGenerationTask,
  StoryGenerationValidation,
  StoryGraphProjection,
  StoryPatchOperation,
  StoryPatchResult,
  StoryPathPreview,
  StoryProjectDocument,
  StoryPublicationResult,
  TaskProgressOptions,
} from "../../shared/platform/types";

export function startStoryGeneration(input: StoryGenerationInput, options?: TaskProgressOptions<StoryGenerationTask>) {
  return getPlatform().story.startGeneration(input, options);
}

export function resumeStoryGeneration(id: string, options?: TaskProgressOptions<StoryGenerationTask>) {
  return getPlatform().story.resumeGeneration(id, options);
}

export function regenerateStoryGeneration(
  id: string,
  stage: StoryGenerationStage,
  options?: TaskProgressOptions<StoryGenerationTask>,
) {
  return getPlatform().story.regenerateGeneration(id, stage, options);
}

export function cancelStoryGeneration(id: string) {
  return getPlatform().story.cancelGeneration(id);
}

export function getStoryGeneration(id: string) {
  return getPlatform().story.getGeneration(id);
}

export function importGeneratedStoryProject(generationTaskId: string) {
  return getPlatform().story.importGeneratedProject(generationTaskId);
}

export function getStoryProject(id: string) {
  return getPlatform().story.getProject(id);
}

export function getStoryProjectGraph(id: string) {
  return getPlatform().story.getProjectGraph(id);
}

export function patchStoryProject(input: {
  allowInvalid?: boolean;
  baseRevision: number;
  commit: boolean;
  id: string;
  patch: { operations: StoryPatchOperation[] };
}): Promise<StoryPatchResult> {
  return getPlatform().story.patchProject(input);
}

export function undoStoryProject(id: string, baseRevision: number): Promise<StoryProjectDocument> {
  return getPlatform().story.undoProject(id, baseRevision);
}

export function validateStoryProject(id: string): Promise<StoryGenerationValidation> {
  return getPlatform().story.validateProject(id);
}

export function previewStoryCast(input: {
  aiProposal?: string[];
  currentCast?: string[];
  id: string;
  nodeId: string;
  playerLocation?: string;
  statuses?: Record<string, { alive?: boolean; available?: boolean; location?: string }>;
}): Promise<StoryCastPreview> {
  return getPlatform().story.previewCast(input);
}

export function previewStoryPath(input: {
  actions?: Array<{ id: string; type: "choice" | "enter" | "intent" }>;
  endingId?: string;
  id: string;
}): Promise<StoryPathPreview> {
  return getPlatform().story.previewPath(input);
}

export function proposeStoryAiPatch(
  input: { baseRevision: number; id: string; instruction: string; region: string },
  options?: TaskProgressOptions<StoryAiPatchProposal>,
) {
  return getPlatform().story.proposeAiPatch(input, options);
}

export function publishStoryProject(id: string, baseRevision: number): Promise<StoryPublicationResult> {
  return getPlatform().story.publishProject(id, baseRevision);
}
