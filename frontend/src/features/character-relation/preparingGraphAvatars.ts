import { prepareGraphAvatar } from "./model/graphAvatar";
import { useEffect, useState } from "react";
import { fileUrl } from "../../entities/files/repository";
import { isVideoMedia } from "../../shared/assets/visualMedia";
import { defaultPortraitCrop } from "../../shared/components/Portrait";
import type { Character, RelationNode } from "../../shared/platform/types";
import { normalizeRelationName } from "./model/relationSelection";

export function usePreparingGraphAvatars(nodes: RelationNode[], characters: Character[] | undefined) {
  const [avatars, setAvatars] = useState<Map<string, HTMLCanvasElement>>(new Map());
  useEffect(() => {
    const controller = new AbortController();
    setAvatars(new Map());
    const names = new Set(nodes.map((node) => normalizeRelationName(node.key)));
    for (const character of characters ?? []) {
      const name = normalizeRelationName(character.name);
      const sprite = character.sprites[0];
      if (!names.has(name) || !sprite?.path) continue;
      const source = fileUrl(sprite.path);
      const url = /^(data:|blob:)/.test(source)
        ? source
        : `${source}${source.includes("?") ? "&" : "?"}avatar_revision=${Date.now()}`;
      const crop = sprite.portrait_crop ?? character.portrait_crop ?? defaultPortraitCrop;
      void prepareGraphAvatar(url, isVideoMedia(sprite.path), crop, controller.signal).then((image) => {
        if (!controller.signal.aborted && image) setAvatars((previous) => new Map(previous).set(name, image));
      });
    }
    return () => controller.abort();
  }, [characters, nodes]);
  return avatars;
}
