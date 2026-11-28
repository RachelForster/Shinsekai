import type { Dispatch, SetStateAction } from "react";

import { listChatThemes } from "../../entities/chat/repository";
import { systemConfigFormSchema, type SchemaErrorMap } from "../../entities/config/schema";
import type { SystemConfig } from "../../entities/config/types";
import type { useI18n } from "../../shared/i18n";

export const systemConfigPageSchema = systemConfigFormSchema
  .map((group) => {
    if (group.id !== "ui") {
      return group;
    }
    return {
      ...group,
      fields: group.fields.filter((field) => field.name !== "ui_language" && field.name !== "chat_ui_theme_id"),
    };
  })
  .filter((group) => group.id !== "voice" && group.id !== "music-cover");

export const systemGeneralGroups = systemConfigPageSchema.filter((group) => group.id === "ui");
export const systemNetworkProxyGroup = systemConfigPageSchema.find((group) => group.id === "network-proxy");
export const systemRemainingGroups = systemConfigPageSchema.filter(
  (group) => group.id !== "ui" && group.id !== "network-proxy",
);

export type SystemChatThemeOption = Awaited<ReturnType<typeof listChatThemes>>[number];

export interface SystemSettingsPageContext {
  chatThemesError: unknown;
  chatThemesIsError: boolean;
  chatThemesLoading: boolean;
  detectNetworkProxyPending: boolean;
  draft: SystemConfig;
  errors: SchemaErrorMap<SystemConfig>;
  openChatThemes: () => void;
  openRuntimeModeDialog: () => void;
  runDetectNetworkProxy: () => void;
  savePending: boolean;
  selectedThemeId: string;
  setDraft: Dispatch<SetStateAction<SystemConfig | null>>;
  showCrossPlatformCard: boolean;
  themeOptions: SystemChatThemeOption[];
}

export function networkProxySourceLabel(source: string, t: ReturnType<typeof useI18n>["t"]) {
  switch (source) {
    case "environment":
      return t("ops.system.proxy.source.env");
    case "process-environment":
      return t("ops.system.proxy.source.processEnv");
    case "windows":
      return t("ops.system.proxy.source.windows");
    case "macos":
      return t("ops.system.proxy.source.macos");
    case "gnome":
      return t("ops.system.proxy.source.gnome");
    case "kde":
      return t("ops.system.proxy.source.kde");
    default:
      return source;
  }
}
