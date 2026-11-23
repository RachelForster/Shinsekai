import type { PageSectionDescriptor } from "../../shared/ui";
import { adapterSchema, hasAdapterSchema } from "./apiSettingsUtils";
import type { ApiSettingsPageContext } from "./apiSettingsContext";
import { ApiAsrPanel } from "./sections/ApiAsrPanel";
import { ApiKnowledgePanel } from "./sections/ApiKnowledgePanel";
import { ApiLanguagePanel } from "./sections/ApiLanguagePanel";
import { ApiLlmPanel } from "./sections/ApiLlmPanel";
import { ApiMemoryPanel } from "./sections/ApiMemoryPanel";
import { ApiPerceptionPanel } from "./sections/ApiPerceptionPanel";
import { ApiResourceLinksPanel } from "./sections/ApiResourceLinksPanel";
import { ApiT2iPanel } from "./sections/ApiT2iPanel";
import { ApiTtsExtraPanel } from "./sections/ApiTtsExtraPanel";
import { ApiTtsPanel } from "./sections/ApiTtsPanel";
import { ApiVisionPanel } from "./sections/ApiVisionPanel";

export const API_SETTINGS_SECTIONS: readonly PageSectionDescriptor<ApiSettingsPageContext>[] = [
  {
    Component: ApiLanguagePanel,
    id: "api-language",
    navLabelKey: "api.language.title",
    order: 10,
  },
  {
    Component: ApiLlmPanel,
    id: "api-llm",
    navLabelKey: "api.nav.llm",
    order: 20,
  },
  {
    Component: ApiTtsPanel,
    id: "api-tts",
    navLabelKey: "api.nav.tts",
    order: 30,
  },
  {
    Component: ApiVisionPanel,
    id: "api-vision",
    navLabelKey: "api.vision.title",
    order: 40,
  },
  {
    Component: ApiPerceptionPanel,
    id: "api-perception",
    navLabelKey: "api.nav.perception",
    order: 50,
  },
  {
    Component: ApiMemoryPanel,
    id: "api-memory",
    navLabelKey: "api.memory.title",
    order: 60,
  },
  {
    Component: ApiKnowledgePanel,
    id: "api-knowledge",
    navLabelKey: "api.knowledge.title",
    order: 70,
  },
  {
    Component: ApiT2iPanel,
    id: "api-t2i",
    navLabelKey: "api.nav.t2i",
    order: 80,
  },
  {
    Component: ApiAsrPanel,
    id: "api-asr",
    navLabelKey: "api.nav.asr",
    order: 90,
  },
  {
    Component: ApiTtsExtraPanel,
    id: "api-tts-extra",
    isVisible: (ctx) => hasAdapterSchema(adapterSchema(ctx.adapterCatalog?.tts, ctx.draft.tts_provider)),
    order: 95,
  },
  {
    Component: ApiResourceLinksPanel,
    id: "api-links",
    navLabelKey: "api.links.title",
    order: 100,
  },
];
