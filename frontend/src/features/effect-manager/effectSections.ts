import type { PageSectionDescriptor } from "../../shared/ui";
import { EffectAmbientSection } from "./sections/EffectAmbientSection";
import { EffectAudioSection } from "./sections/EffectAudioSection";
import { EffectImagesSection } from "./sections/EffectImagesSection";
import { EffectInfoSection } from "./sections/EffectInfoSection";
import type { EffectPageContext } from "./effectContext";

export const EFFECT_MANAGER_SECTIONS: readonly PageSectionDescriptor<EffectPageContext>[] = [
  {
    Component: EffectInfoSection,
    id: "effect-info",
    navLabelKey: "effect.section.info",
    order: 10,
  },
  {
    Component: EffectImagesSection,
    id: "effect-images",
    navLabelKey: "effect.section.image",
    order: 20,
  },
  {
    Component: EffectAmbientSection,
    id: "effect-ambient",
    navLabelKey: "effect.section.ambient",
    order: 30,
  },
  {
    Component: EffectAudioSection,
    id: "effect-audio",
    navLabelKey: "effect.section.audio",
    order: 40,
  },
];
