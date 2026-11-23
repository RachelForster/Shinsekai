import { useCallback, useRef } from "react";

import { DEFAULT_CHARACTER_COLOR } from "../../../shared/constants";
import type { PageSectionProps } from "../../../shared/ui";
import { CharacterBasicSection } from "../CharacterBasicSection";
import type { CharacterPageContext } from "../characterContext";

export function CharacterBasicPanel({ ctx, id }: PageSectionProps<CharacterPageContext>) {
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(ctx.draft.color || "") ? ctx.draft.color : DEFAULT_CHARACTER_COLOR;
  const setColorInputElement = useCallback((element: HTMLInputElement | null) => {
    colorInputRef.current = element;
  }, []);
  const openColorPicker = useCallback(() => {
    colorInputRef.current?.click();
  }, []);

  return (
    <CharacterBasicSection
      colorPickerValue={colorPickerValue}
      draft={ctx.draft}
      id={id}
      identityConfirmDisabled={ctx.aiActionPending}
      identitySavingField={ctx.identitySavingField}
      nameDirty={ctx.nameDirty}
      nameError={ctx.liveNameError}
      onCancelName={() => ctx.cancelIdentityField("name")}
      onCancelSpritePrefix={() => ctx.cancelIdentityField("sprite_prefix")}
      onChange={ctx.updateField}
      onColorInputRef={setColorInputElement}
      onConfirmName={() => ctx.confirmIdentityField("name")}
      onConfirmSpritePrefix={() => ctx.confirmIdentityField("sprite_prefix")}
      onDelete={ctx.requestCharacterDelete}
      onPickColor={openColorPicker}
      onPronunciationTextChange={ctx.setPronunciationText}
      pronunciationText={ctx.pronunciationText}
      spritePrefixDirty={ctx.spritePrefixDirty}
      spritePrefixError={ctx.liveSpritePrefixError}
    />
  );
}
