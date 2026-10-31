import { tagContents } from "../../shared/assets/assetText";
import type { Character } from "../../shared/platform/types";
import type { SpriteCandidate } from "./useSpriteGeneration";

export interface SpriteAnimationSource {
  id: string;
  referenceImage: string;
  tagging: string;
  origin: "existing" | "generated";
  index: number;
}

export function spriteAnimationSources(character: Character, candidates: SpriteCandidate[]): SpriteAnimationSource[] {
  const tags = tagContents(character.emotion_tags, character.sprites.length);
  return [
    ...candidates.flatMap((item, index) =>
      item.result && item.result.prompt === item.prompt
        ? [
            {
              id: `generated:${item.id}`,
              referenceImage: item.result.path,
              tagging: item.tagging,
              origin: "generated" as const,
              index,
            },
          ]
        : [],
    ),
    ...character.sprites.flatMap((sprite, index) =>
      sprite.path
        ? [
            {
              id: `existing:${index}:${sprite.path}`,
              referenceImage: sprite.path,
              tagging: tags[index],
              origin: "existing" as const,
              index,
            },
          ]
        : [],
    ),
  ];
}
