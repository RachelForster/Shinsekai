import type { PageSectionProps } from "../../../shared/ui";
import { ModelStateEditor } from "../ModelStateEditor";
import type { CharacterPageContext } from "../characterContext";

export function CharacterModelStatePanel({ ctx }: PageSectionProps<CharacterPageContext>) {
  return <ModelStateEditor character={ctx.draft} onChange={ctx.patchDraft} onSaved={ctx.syncModelStateCharacter} />;
}
