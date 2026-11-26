import type { PageSectionProps } from "../../../shared/ui";
import { CharacterRelationSection } from "../../character-relation/view/CharacterRelationSection";
import type { CharacterPageContext } from "../characterContext";

export function CharacterRelationPanel({ ctx }: PageSectionProps<CharacterPageContext>) {
  return (
    <CharacterRelationSection
      key={ctx.currentCharacterName || "new"}
      primary={ctx.isSavedCharacter ? ctx.currentCharacterName : ""}
    />
  );
}
