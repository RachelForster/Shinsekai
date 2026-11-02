import type { MessageKey } from "../../../shared/i18n";
import type { StoryGenerationStage } from "../../../entities/story/types";

export const stages: Array<{ id: StoryGenerationStage; label: MessageKey; description: MessageKey }> = [
  { id: "foundation", label: "story.stage.foundation", description: "story.stage.foundationHint" },
  { id: "characters", label: "story.stage.characters", description: "story.stage.charactersHint" },
  { id: "narrative", label: "story.stage.narrative", description: "story.stage.narrativeHint" },
];
export const taskStatus = {
  queued: "story.status.queued",
  running: "story.status.running",
  succeeded: "story.status.succeeded",
  failed: "story.status.failed",
  cancelled: "story.status.cancelled",
} as const;
