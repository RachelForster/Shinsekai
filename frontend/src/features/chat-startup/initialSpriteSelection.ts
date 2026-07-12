import type { Character } from "../../shared/platform/types";

function browserHostPlatform() {
  if (typeof navigator === "undefined") {
    return "";
  }
  const userAgentData = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData;
  return userAgentData?.platform || navigator.platform || navigator.userAgent;
}

export function spritePathsAreCaseSensitive(platform = browserHostPlatform()) {
  return !/\bwin(?:32|64|dows|ce)?\b/iu.test(platform.trim());
}

function normalizedSpritePath(path: string, caseSensitive: boolean) {
  const normalized = path.trim().replaceAll("\\", "/");
  return caseSensitive ? normalized : normalized.toLowerCase();
}

export function initialSpriteOwner(
  path: string,
  characters: Array<Pick<Character, "name" | "sprites">>,
  { caseSensitive = spritePathsAreCaseSensitive() }: { caseSensitive?: boolean } = {},
) {
  const normalizedPath = normalizedSpritePath(path, caseSensitive);
  if (!normalizedPath) {
    return undefined;
  }
  return characters.find((character) =>
    (character?.sprites ?? []).some(
      (sprite) =>
        typeof sprite?.path === "string" && normalizedSpritePath(sprite.path, caseSensitive) === normalizedPath,
    ),
  )?.name;
}

export function compatibleInitialSpritePath({
  characters,
  caseSensitive = spritePathsAreCaseSensitive(),
  path,
  preserveUnknown = true,
  selectedCharacters,
}: {
  characters: Array<Pick<Character, "name" | "sprites">>;
  caseSensitive?: boolean;
  path: string;
  preserveUnknown?: boolean;
  selectedCharacters: string[];
}) {
  const candidate = path.trim();
  if (!candidate) {
    return "";
  }
  const owner = initialSpriteOwner(candidate, characters, { caseSensitive });
  if (!owner) {
    return preserveUnknown ? candidate : "";
  }
  return selectedCharacters.includes(owner) ? candidate : "";
}
