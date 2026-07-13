import { useQuery } from "@tanstack/react-query";

import { listPlugins, pluginsQueryKey } from "../../entities/plugin/repository";
import type { PluginManifest } from "../../entities/plugin/types";

const MOONDREAM_PLUGIN_ID = "com.shinsekai.moondream_vision";
const MOONDREAM_PLUGIN_ENTRY = "plugins.moondream_vision.plugin:MoondreamVisionPlugin";

export function isMoondreamInstalled(plugin: PluginManifest) {
  const directory = (plugin.directory ?? "").replaceAll("\\", "/").replace(/\/$/, "");
  const entry = plugin.entry.startsWith("plugins.") ? plugin.entry : `plugins.${plugin.entry}`;
  return (
    plugin.id === MOONDREAM_PLUGIN_ID ||
    entry === MOONDREAM_PLUGIN_ENTRY ||
    directory === "plugins/moondream_vision" ||
    directory.endsWith("/plugins/moondream_vision")
  );
}

export function useMoondreamAvailability() {
  const query = useQuery({ queryFn: listPlugins, queryKey: pluginsQueryKey, staleTime: 30_000 });
  return Boolean(query.data?.some(isMoondreamInstalled));
}
