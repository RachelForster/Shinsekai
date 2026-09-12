import { getPlatform } from "../../shared/platform/platform";
import type {
  StoryGenerationInput,
  StoryGenerationStage,
  StoryGenerationTask,
  TaskProgressOptions,
} from "../../shared/platform/types";

export const storyLibraryQueryKey = ["story-library"] as const;

export function listStories() {
  return getPlatform().story.list();
}

export function prepareStoryLaunch(storyPath: string, historyPath?: string) {
  return getPlatform().story.prepareLaunch(storyPath, historyPath);
}

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

export function getStoryPreview(id: string) {
  return getPlatform().story.getPreview(id);
}

export function startStorySession(storyPath: string) {
  return getPlatform().story.startSession(storyPath);
}
