import type { CSSProperties } from "react";

import type { ChatStageSprite } from "./chatState";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";

export const clickThroughGuardIntervalMs = 32;
const runtimeConfigStorageKey = "shinsekai-chat-stage-runtime-config";
export const runtimeTextSpeedMin = 1;
export const runtimeTextSpeedMax = 200;
export const runtimeDialogOpacityMin = 0.35;
export const runtimeDialogOpacityMax = 1;
export const runtimeDialogOpacityStep = 0.05;
export const runtimeDialogScaleMin = 0.8;
export const runtimeDialogScaleMax = 1.2;
export const runtimeDialogScaleStep = 0.05;
export const runtimeSpriteDefaultScaleKey = "__default__";
export const runtimeSpriteScaleMin = 0;
export const runtimeSpriteScaleMax = 3;
export const runtimeSpriteScaleStep = 0.05;
export const runtimeSpriteOffsetMin = -240;
export const runtimeSpriteOffsetMax = 240;
export const runtimeSpriteOffsetStep = 4;
export const runtimeWindowScaleMin = 0.8;
export const runtimeWindowScaleMax = 1.2;
export const runtimeWindowScaleStep = 0.05;

export interface ChatStageRuntimeConfig {
  auto: boolean;
  dialogOpacity: number;
  dialogScale: number;
  spriteScales: Record<string, number>;
  spriteOffsetX: number;
  spriteOffsetY: number;
  typewriterCps: number | null;
  windowScale: number;
}

export const defaultChatStageRuntimeConfig: ChatStageRuntimeConfig = {
  auto: false,
  dialogOpacity: 1,
  dialogScale: 1,
  spriteScales: {},
  spriteOffsetX: 0,
  spriteOffsetY: 0,
  typewriterCps: null,
  windowScale: 1,
};

export function clampRuntimeNumber(value: unknown, fallback: number, min: number, max: number) {
  const next = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(next)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, next));
}

function readRuntimeSpriteScales(parsed: Partial<ChatStageRuntimeConfig> & { spriteScale?: unknown }) {
  const spriteScales: Record<string, number> = {};
  const rawSpriteScales = parsed.spriteScales;
  if (rawSpriteScales && typeof rawSpriteScales === "object" && !Array.isArray(rawSpriteScales)) {
    for (const [key, value] of Object.entries(rawSpriteScales)) {
      const trimmedKey = key.trim();
      if (!trimmedKey) {
        continue;
      }
      spriteScales[trimmedKey] = clampRuntimeNumber(value, 1, runtimeSpriteScaleMin, runtimeSpriteScaleMax);
    }
  }
  if (!Object.keys(spriteScales).length && parsed.spriteScale != null) {
    spriteScales[runtimeSpriteDefaultScaleKey] = clampRuntimeNumber(
      parsed.spriteScale,
      1,
      runtimeSpriteScaleMin,
      runtimeSpriteScaleMax,
    );
  }
  return spriteScales;
}

export function readChatStageRuntimeConfig(): ChatStageRuntimeConfig {
  if (typeof window === "undefined") {
    return defaultChatStageRuntimeConfig;
  }
  try {
    const raw = window.localStorage.getItem(runtimeConfigStorageKey);
    if (!raw) {
      return defaultChatStageRuntimeConfig;
    }
    const parsed = JSON.parse(raw) as Partial<ChatStageRuntimeConfig>;
    return {
      auto: typeof parsed.auto === "boolean" ? parsed.auto : defaultChatStageRuntimeConfig.auto,
      dialogOpacity: clampRuntimeNumber(
        parsed.dialogOpacity,
        defaultChatStageRuntimeConfig.dialogOpacity,
        runtimeDialogOpacityMin,
        runtimeDialogOpacityMax,
      ),
      dialogScale: clampRuntimeNumber(
        parsed.dialogScale,
        defaultChatStageRuntimeConfig.dialogScale,
        runtimeDialogScaleMin,
        runtimeDialogScaleMax,
      ),
      typewriterCps:
        parsed.typewriterCps == null
          ? null
          : Math.round(
              clampRuntimeNumber(
                parsed.typewriterCps,
                DEFAULT_TYPEWRITER_CPS,
                runtimeTextSpeedMin,
                runtimeTextSpeedMax,
              ),
            ),
      spriteScales: readRuntimeSpriteScales(parsed),
      spriteOffsetX: Math.round(
        clampRuntimeNumber(
          parsed.spriteOffsetX,
          defaultChatStageRuntimeConfig.spriteOffsetX,
          runtimeSpriteOffsetMin,
          runtimeSpriteOffsetMax,
        ),
      ),
      spriteOffsetY: Math.round(
        clampRuntimeNumber(
          parsed.spriteOffsetY,
          defaultChatStageRuntimeConfig.spriteOffsetY,
          runtimeSpriteOffsetMin,
          runtimeSpriteOffsetMax,
        ),
      ),
      windowScale: clampRuntimeNumber(
        parsed.windowScale,
        defaultChatStageRuntimeConfig.windowScale,
        runtimeWindowScaleMin,
        runtimeWindowScaleMax,
      ),
    };
  } catch {
    return defaultChatStageRuntimeConfig;
  }
}

export function writeChatStageRuntimeConfig(config: ChatStageRuntimeConfig) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(runtimeConfigStorageKey, JSON.stringify(config));
  } catch {
    // localStorage may be unavailable in hardened webviews.
  }
}

export function runtimeSpriteKey(sprite: ChatStageSprite, index: number) {
  return sprite.id || sprite.characterName || sprite.label || `slot-${sprite.slot ?? index}`;
}

export function runtimeSpriteLabel(sprite: ChatStageSprite, index: number) {
  return sprite.label || sprite.characterName || sprite.id || `#${index + 1}`;
}

export function runtimeSpriteScale(config: ChatStageRuntimeConfig, sprite: ChatStageSprite, index: number) {
  const key = runtimeSpriteKey(sprite, index);
  return config.spriteScales[key] ?? config.spriteScales[runtimeSpriteDefaultScaleKey] ?? 1;
}

export function chatStageRuntimeStyle(config: ChatStageRuntimeConfig, themeStyle: CSSProperties): CSSProperties {
  return {
    ...themeStyle,
    "--chat-dialog-runtime-opacity": String(config.dialogOpacity),
    "--chat-dialog-runtime-scale": String(config.dialogScale),
    "--chat-dialog-runtime-width": `${Math.round(1040 * config.windowScale)}px`,
    "--chat-sprite-runtime-offset-x": `${config.spriteOffsetX}px`,
    "--chat-sprite-runtime-offset-y": `${config.spriteOffsetY}px`,
    "--chat-ui-runtime-width": `${Math.round(1120 * config.windowScale)}px`,
    "--chat-ui-window-scale": String(config.windowScale),
  } as CSSProperties;
}
