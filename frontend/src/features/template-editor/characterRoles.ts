import type { CharacterPromptMode } from "../../shared/platform/types";

export function updateCharacterRoles(
  previous: string[],
  next: string[],
  primary: string[],
  mode?: CharacterPromptMode,
): { primary: string[]; mode: CharacterPromptMode | undefined } {
  if (next.length <= 4) return { primary: next, mode: "full" };
  const remaining = primary.filter((name) => next.includes(name));
  const keepMode = !next.some((name) => !previous.includes(name)) && (mode === "full" || remaining.length > 0);
  return { primary: remaining, mode: keepMode ? mode : undefined };
}
