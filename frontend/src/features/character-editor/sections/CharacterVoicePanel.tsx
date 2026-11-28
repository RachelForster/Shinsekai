import type { PageSectionProps } from "../../../shared/ui";
import { CharacterVoiceSection } from "../CharacterVoiceSection";
import { removeCharacterVoice } from "../characterEditorUtils";
import type { CharacterPageContext } from "../characterContext";

export function CharacterVoicePanel({ ctx, id }: PageSectionProps<CharacterPageContext>) {
  return (
    <CharacterVoiceSection
      key={ctx.draft.id ?? ctx.draft.name}
      draft={ctx.draft}
      voiceProfilesEnabled={ctx.voiceProfilesEnabled}
      id={id}
      onChange={ctx.updateField}
      onRemoveProfile={(profileId) => ctx.patchDraft((current) => removeCharacterVoice(current, profileId))}
      voiceReferenceReadOnly={ctx.voiceReferenceReadOnly}
    />
  );
}
