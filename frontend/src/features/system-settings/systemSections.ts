import type { SystemConfig } from "../../entities/config/types";
import { isTauriDesktop } from "../../shared/desktop/desktopApi";
import type { FormGroupSchema } from "../../shared/form-schema";
import type { PageSectionDescriptor } from "../../shared/ui";
import { SystemChatThemeSection } from "./sections/SystemChatThemeSection";
import { SystemNetworkProxySection } from "./sections/SystemNetworkProxySection";
import {
  SystemCrossPlatformSection,
  SystemDesktopBackgroundSection,
  SystemDesktopRuntimeSection,
} from "./sections/SystemRuntimeSections";
import { createSystemGroupComponent } from "./sections/SystemSchemaSections";
import {
  systemGeneralGroups,
  systemNetworkProxyGroup,
  systemRemainingGroups,
  type SystemSettingsPageContext,
} from "./systemSettingsContext";

function createSchemaGroupDescriptor(
  group: FormGroupSchema<SystemConfig>,
  order: number,
): PageSectionDescriptor<SystemSettingsPageContext> {
  return {
    Component: createSystemGroupComponent(group),
    id: `system-${group.id}`,
    navLabel: group.title,
    navLabelKey: group.titleKey,
    order,
  };
}

export const SYSTEM_SETTINGS_SECTIONS: readonly PageSectionDescriptor<SystemSettingsPageContext>[] = [
  {
    Component: SystemDesktopRuntimeSection,
    id: "system-runtime",
    isVisible: () => isTauriDesktop(),
    navLabelKey: "system.runtime.title",
    order: 10,
  },
  {
    Component: SystemDesktopBackgroundSection,
    id: "system-background",
    isVisible: () => isTauriDesktop(),
    navLabelKey: "desktop.background.title",
    order: 20,
  },
  {
    Component: SystemCrossPlatformSection,
    id: "system-cross-platform",
    isVisible: (ctx) => ctx.showCrossPlatformCard,
    order: 30,
  },
  ...systemGeneralGroups.map((group, index) => createSchemaGroupDescriptor(group, 40 + index)),
  {
    Component: SystemChatThemeSection,
    id: "system-chat-theme",
    navLabelKey: "chat.theme.title",
    order: 50,
  },
  {
    Component: SystemNetworkProxySection,
    id: "system-network-proxy",
    isVisible: () => Boolean(systemNetworkProxyGroup),
    navLabel: systemNetworkProxyGroup?.title,
    navLabelKey: systemNetworkProxyGroup?.titleKey,
    order: 60,
  },
  ...systemRemainingGroups.map((group, index) => createSchemaGroupDescriptor(group, 70 + index * 10)),
];
