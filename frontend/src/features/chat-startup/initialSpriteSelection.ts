import type { Character } from "../../shared/platform/types";
import { characterAssetBanks, getCharacterAssets, type CharacterAssetSource } from "../../entities/character/assets";

type SpriteCharacter = Pick<Character, "name" | "sprites"> & CharacterAssetSource;

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
  characters: SpriteCharacter[],
  {
    caseSensitive = spritePathsAreCaseSensitive(),
    includeInactive = false,
  }: { caseSensitive?: boolean; includeInactive?: boolean } = {},
) {
  const normalizedPath = normalizedSpritePath(path, caseSensitive);
  if (!normalizedPath) {
    return undefined;
  }
  return characters.find((character) =>
    (includeInactive ? characterAssetBanks(character) : [getCharacterAssets(character)]).some((bank) =>
      bank.sprites.some(
        (sprite) =>
          typeof sprite?.path === "string" && normalizedSpritePath(sprite.path, caseSensitive) === normalizedPath,
      ),
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
  characters: SpriteCharacter[];
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
    if (initialSpriteOwner(candidate, characters, { caseSensitive, includeInactive: true })) return "";
    return preserveUnknown ? candidate : "";
  }
  return selectedCharacters.includes(owner) ? candidate : "";
}
