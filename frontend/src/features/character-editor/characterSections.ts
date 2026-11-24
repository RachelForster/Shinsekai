import type { PageSectionDescriptor } from "../../shared/ui";
import type { CharacterPageContext, CharacterSectionSlot } from "./characterContext";
import { CharacterBasicPanel } from "./sections/CharacterBasicPanel";
import { CharacterMemoryPanel } from "./sections/CharacterMemoryPanel";
import { CharacterModelStatePanel } from "./sections/CharacterModelStatePanel";
import { CharacterPersonalityPanel } from "./sections/CharacterPersonalityPanel";
import { CharacterRelationPanel } from "./sections/CharacterRelationPanel";
import { CharacterSpritesPanel } from "./sections/CharacterSpritesPanel";
import { CharacterVoicePanel } from "./sections/CharacterVoicePanel";

export const CHARACTER_EDITOR_SECTIONS: readonly PageSectionDescriptor<CharacterPageContext, CharacterSectionSlot>[] = [
  {
    Component: CharacterBasicPanel,
    id: "character-basic",
    navLabelKey: "character.section.basic",
    order: 10,
    slot: "top-grid",
  },
  {
    Component: CharacterPersonalityPanel,
    id: "character-personality",
    navLabelKey: "character.section.personality",
    order: 20,
    slot: "top-grid",
  },
  {
    Component: CharacterVoicePanel,
    id: "character-voice",
    navLabelKey: "character.section.voice",
    order: 30,
    slot: "body",
  },
  {
    Component: CharacterModelStatePanel,
    id: "character-model-state",
    order: 35,
    slot: "body",
  },
  {
    Component: CharacterSpritesPanel,
    id: "character-sprites",
    isVisible: (ctx) => ctx.draft.avatar_type === "static",
    navLabelKey: "character.section.sprites",
    order: 40,
    slot: "body",
  },
  {
    Component: CharacterMemoryPanel,
    id: "character-memory",
    navLabelKey: "character.memory.section",
    order: 50,
    slot: "body",
  },
  {
    Component: CharacterRelationPanel,
    id: "character-relations",
    navLabelKey: "relation.title",
    order: 60,
    slot: "body",
  },
];
