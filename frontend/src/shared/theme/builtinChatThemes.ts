import neonNightCityThemeJson from "../../../../assets/chat_ui_themes/neon-night-city/theme.json";
import sakuraDreamThemeJson from "../../../../assets/chat_ui_themes/sakura-dream/theme.json";
import windborneAdventureThemeJson from "../../../../assets/chat_ui_themes/windborne-adventure/theme.json";

import { CHAT_THEME_SCHEMA, type ChatThemeManifest } from "./chatTheme";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function bundledThemeManifest(value: unknown): ChatThemeManifest {
  if (!isRecord(value) || value.schema !== CHAT_THEME_SCHEMA || typeof value.id !== "string") {
    throw new Error("Invalid bundled chat theme manifest");
  }
  if (!isRecord(value.name) || !isRecord(value.tokens)) {
    throw new Error(`Invalid bundled chat theme manifest: ${value.id}`);
  }

  const { $schema: _schema, ...manifest } = value;
  return manifest as unknown as ChatThemeManifest;
}

const bundledThemeManifests = [
  bundledThemeManifest(windborneAdventureThemeJson),
  bundledThemeManifest(neonNightCityThemeJson),
  bundledThemeManifest(sakuraDreamThemeJson),
];

export const builtinChatThemeManifests: Record<string, ChatThemeManifest> = Object.fromEntries(
  bundledThemeManifests.map((manifest) => [manifest.id, manifest]),
);
