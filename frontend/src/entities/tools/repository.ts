import { getPlatform } from "../../shared/platform/platform";
import type {
  BatchToolResult,
  SpriteGenerationResult,
  SpritePromptResult,
  TaskProgressOptions,
} from "../../shared/platform/types";

export function generateSpritePrompts(
  input: { characterName: string; count: number; language?: string; positivePromptReference?: string },
  options?: TaskProgressOptions<SpritePromptResult>,
) {
  return getPlatform().tools.generateSpritePrompts(input, options);
}

export function generateSprites(
  input: { characterName: string; outputDir?: string; prompts: string[]; referenceImage: string },
  options?: TaskProgressOptions<SpriteGenerationResult>,
) {
  return getPlatform().tools.generateSprites(input, options);
}

export function generateSpriteImage(
  input: { characterName: string; label?: string; negativePrompt?: string; outputDir?: string; prompt: string },
  options?: TaskProgressOptions<SpriteGenerationResult>,
) {
  return getPlatform().tools.generateSpriteImage(input, options);
}

export function cropSprites(
  input: { inputDir: string; outputDir?: string; ratio: number },
  options?: TaskProgressOptions<BatchToolResult>,
) {
  return getPlatform().tools.cropSprites(input, options);
}

export function removeSpriteBackground(
  input: { inputDir: string; outputDir?: string },
  options?: TaskProgressOptions<BatchToolResult>,
) {
  return getPlatform().tools.removeSpriteBackground(input, options);
}
