import type { ChatStoryState } from "../../../shared/platform/types";

export function StoryDebugPanel({ story }: { story?: ChatStoryState }) {
  if (!story) {
    return null;
  }
  return (
    <details className="story-debug-panel" data-chat-stage-hitbox="true">
      <summary>Story · {story.currentNodeTitle}</summary>
      <dl>
        <div>
          <dt>Node</dt>
          <dd>{story.currentNodeId}</dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd>{story.revision}</dd>
        </div>
        <div>
          <dt>Cast</dt>
          <dd>{story.activeCast.map((character) => character.id).join(", ") || "—"}</dd>
        </div>
      </dl>
    </details>
  );
}
