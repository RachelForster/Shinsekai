import type { Character } from "../../shared/platform/types";

function normalizedSpritePath(path: string) {
  return path.trim().replaceAll("\\", "/").toLowerCase();
}

export function initialSpriteOwner(path: string, characters: Array<Pick<Character, "name" | "sprites">>) {
  const normalizedPath = normalizedSpritePath(path);
  if (!normalizedPath) {
    return undefined;
  }
  return characters.find((character) =>
    (character?.sprites ?? []).some(
      (sprite) => typeof sprite?.path === "string" && normalizedSpritePath(sprite.path) === normalizedPath,
    ),
  )?.name;
}

export function compatibleInitialSpritePath({
  characters,
  path,
  preserveUnknown = true,
  selectedCharacters,
}: {
  characters: Array<Pick<Character, "name" | "sprites">>;
  path: string;
  preserveUnknown?: boolean;
  selectedCharacters: string[];
}) {
  const candidate = path.trim();
  if (!candidate) {
    return "";
  }
  const owner = initialSpriteOwner(candidate, characters);
  if (!owner) {
    return preserveUnknown ? candidate : "";
  }
  return selectedCharacters.includes(owner) ? candidate : "";
}
