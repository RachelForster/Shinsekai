import type { PageSectionDescriptor } from "../../shared/ui";
import type { TemplateEditorContext, TemplateSectionSlot } from "./templateContext";
import { TemplateCharactersSection } from "./sections/TemplateCharactersSection";
import { TemplatePresetPromptsSection } from "./sections/TemplatePresetPromptsSection";
import { TemplateRuntimeSection } from "./sections/TemplateRuntimeSection";
import { TemplateStageSection } from "./sections/TemplateStageSection";
import { TemplateSystemPromptSection } from "./sections/TemplateSystemPromptSection";
import { TemplateUserPromptSection } from "./sections/TemplateUserPromptSection";

export const TEMPLATE_EDITOR_SECTIONS: readonly PageSectionDescriptor<TemplateEditorContext, TemplateSectionSlot>[] = [
  {
    Component: TemplateCharactersSection,
    id: "characters",
    order: 10,
    slot: "main",
  },
  {
    Component: TemplatePresetPromptsSection,
    id: "preset-prompts",
    order: 20,
    slot: "main",
  },
  {
    Component: TemplateSystemPromptSection,
    id: "system-prompt",
    order: 30,
    slot: "main",
  },
  {
    Component: TemplateUserPromptSection,
    id: "user-prompt",
    order: 40,
    slot: "main",
  },
  {
    Component: TemplateStageSection,
    id: "stage",
    order: 10,
    slot: "sidebar",
  },
  {
    Component: TemplateRuntimeSection,
    id: "runtime",
    order: 20,
    slot: "sidebar",
  },
];
