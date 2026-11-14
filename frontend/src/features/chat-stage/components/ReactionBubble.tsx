import { useEffect, useState, type CSSProperties } from "react";

import { chatStageSpriteAxisCenter, chatStageSpriteCharacterName } from "../state/sprites";
import type { ChatStageSprite, ChatStageSpriteReaction } from "../state/types";

export function ReactionBubble({
  hidden = false,
  reaction,
  sprites,
}: {
  hidden?: boolean;
  reaction?: ChatStageSpriteReaction | null;
  sprites: readonly ChatStageSprite[];
}) {
  const [timing, setTiming] = useState<{ elapsed: number; seq: number } | null>(null);

  useEffect(() => {
    const remaining = (reaction?.deadline ?? 0) - performance.now();
    if (!reaction?.text || remaining <= 0) {
      setTiming(null);
      return;
    }
    setTiming({
      elapsed: Math.max(0, reaction.durationMs - remaining),
      seq: reaction.seq,
    });
    const timer = window.setTimeout(() => setTiming(null), remaining);
    return () => window.clearTimeout(timer);
  }, [reaction?.deadline, reaction?.durationMs, reaction?.seq, reaction?.text]);

  if (hidden || !reaction?.text || !timing || timing.seq !== reaction.seq) {
    return null;
  }

  const targetName = reaction.characterName.trim();
  const matchedIndex = targetName
    ? sprites.findIndex((sprite) => chatStageSpriteCharacterName(sprite) === targetName)
    : -1;
  const fallbackIndex = matchedIndex >= 0 ? matchedIndex : sprites.length === 1 ? 0 : -1;
  const targetSprite = fallbackIndex >= 0 ? sprites[fallbackIndex] : undefined;
  const axisCenter = targetSprite ? chatStageSpriteAxisCenter(sprites, targetSprite, fallbackIndex) : 50;
  const spriteOffsetX = targetSprite?.x ?? 0;
  const showSpeakerBadge = Boolean(targetName) && sprites.length > 1;

  return (
    <aside
      aria-live="polite"
      className="sprite-reaction-bubble"
      data-chat-stage-reaction="true"
      key={reaction.seq}
      role="status"
      style={
        {
          "--reaction-axis-center": `${axisCenter}%`,
          "--reaction-offset-x": `${spriteOffsetX}px`,
          animationDelay: `-${timing.elapsed}ms`,
          animationDuration: `${reaction.durationMs}ms`,
        } as CSSProperties
      }
    >
      {showSpeakerBadge ? <span className="sprite-reaction-bubble__speaker">{targetName}</span> : null}
      <span className="sprite-reaction-bubble__text">{reaction.text}</span>
    </aside>
  );
}
