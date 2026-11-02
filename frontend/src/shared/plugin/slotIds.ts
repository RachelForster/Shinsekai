import type { PluginSlotId } from "../platform/types";

export const pluginSlotIds: PluginSlotId[] = [
  "chat-dialog-actions",
  "chat-output",
  "chat-toolbar",
  "chat-top-toolbar",
  "settings-extension",
  "settings-tools",
];

export function isPluginSlotId(value: string): value is PluginSlotId {
  return pluginSlotIds.includes(value as PluginSlotId);
}
