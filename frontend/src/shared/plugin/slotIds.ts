import type { PluginSlotId } from "../platform/types";

export const pluginSlotIds: PluginSlotId[] = [
  "api-header-actions",
  "app-topbar-actions",
  "background-header-actions",
  "character-header-actions",
  "chat-dialog-actions",
  "chat-output",
  "chat-toolbar",
  "chat-top-toolbar",
  "chat-workspace-actions",
  "effect-header-actions",
  "settings-extension",
  "settings-tools",
  "system-header-actions",
  "template-header-actions",
];

export function isPluginSlotId(value: string): value is PluginSlotId {
  return pluginSlotIds.includes(value as PluginSlotId);
}
