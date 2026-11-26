import type { PageSectionDescriptor } from "../../shared/ui";
import type { BackgroundPageContext } from "./backgroundContext";
import { BackgroundBgmSection } from "./sections/BackgroundBgmSection";
import { BackgroundImagesSection } from "./sections/BackgroundImagesSection";
import { BackgroundInfoSection } from "./sections/BackgroundInfoSection";
import { BackgroundKnowledgeSection } from "./sections/BackgroundKnowledgeSection";

export const BACKGROUND_MANAGER_SECTIONS: readonly PageSectionDescriptor<BackgroundPageContext>[] = [
  {
    Component: BackgroundInfoSection,
    id: "background-info",
    navLabelKey: "background.section.info",
    order: 10,
  },
  {
    Component: BackgroundImagesSection,
    id: "background-images",
    navLabelKey: "background.section.images",
    order: 20,
  },
  {
    Component: BackgroundBgmSection,
    id: "background-bgm",
    navLabelKey: "background.section.bgm",
    order: 30,
  },
  {
    Component: BackgroundKnowledgeSection,
    id: "background-knowledge",
    navLabelKey: "knowledge.title",
    order: 40,
  },
];
