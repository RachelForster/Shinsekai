import type { FrontendLanguage } from "../../shared/i18n";

export type ReleaseHighlightIcon = "copy" | "palette" | "preview";

export interface ReleaseHighlightFeature {
  description: string;
  icon: ReleaseHighlightIcon;
  image?: string;
  title: string;
}

export interface ReleaseHighlightContent {
  actionLabel?: string;
  actionTo?: string;
  features: ReleaseHighlightFeature[];
  summary: string;
  title: string;
}

export interface ReleaseHighlight {
  content: Record<FrontendLanguage, ReleaseHighlightContent>;
  version: string;
}
