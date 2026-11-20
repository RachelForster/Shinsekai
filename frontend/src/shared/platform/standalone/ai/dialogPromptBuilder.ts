import type { Character } from "../../slices/characterTypes";
import type { CharacterOutfitState, ChatLaunchPayload, ChatStat } from "../../slices/chatTypes";
import type { SystemConfig } from "../../slices/configTypes";
import type { Background, Effect } from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";
import {
  DEFAULT_EMPTY_SCENARIO,
  buildStandaloneEffectCatalogBlock,
  generateStandaloneDialogSystemTemplate,
} from "./templateGenerator";

export interface StandalonePromptContext {
  characters: Character[];
  backgrounds?: Background[];
  effects?: Effect[];
  systemConfig?: Partial<SystemConfig>;
  payload: ChatLaunchPayload;
  outfits?: Record<string, CharacterOutfitState>;
  stats?: ChatStat[];
  userDisplayName?: string;
}

function buildRuntimeStateSupplement(
  characters: Character[],
  outfits: Record<string, CharacterOutfitState> | undefined,
  stats: ChatStat[] | undefined,
  userDisplayName: string | undefined,
  playerCharacter: string | undefined,
): string {
  const lines: string[] = [];
  const activePlayer = userDisplayName || playerCharacter || "";
  if (activePlayer) {
    lines.push(`【当前主控称呼】${activePlayer}`);
  }
  if (outfits) {
    const outfitLines: string[] = [];
    for (const char of characters) {
      const state = outfits[char.name];
      if (!state?.activeGroup) continue;
      const defaultGroup = char.default_sprite_group || "默认";
      if (state.activeGroup !== defaultGroup || state.locked || (char.sprite_groups?.length ?? 0) > 1) {
        outfitLines.push(`${char.name}: ${state.activeGroup}${state.locked ? "（已锁定，请勿更换）" : ""}`);
      }
    }
    if (outfitLines.length) {
      lines.push(`【当前服装状态】${outfitLines.join("；")}`);
    }
  }
  if (stats?.length) {
    const statSummary = stats.map((s) => `${s.label}: ${s.value}${s.max !== undefined ? `/${s.max}` : ""}`).join("，");
    lines.push(`【当前舞台数值】${statSummary}`);
  }
  return lines.join("\n");
}

export function buildStandaloneDialogSystemPrompt(ctx: StandalonePromptContext): string {
  const {
    characters,
    backgrounds = [],
    effects = [],
    systemConfig = {},
    payload,
    outfits,
    stats,
    userDisplayName,
  } = ctx;
  const uiLanguage = systemConfig.ui_language || "zh_CN";
  const t = createStandaloneTemplateTranslator(uiLanguage);

  let systemTemplate = (payload.system ?? "").trim();
  if (!systemTemplate) {
    if (characters.length > 0) {
      const generated = generateStandaloneDialogSystemTemplate({
        input: {
          name: payload.templateName || "runtime",
          characters: characters.map((c) => c.name),
          primaryCharacters: payload.primaryCharacters,
          characterPromptMode: payload.characterPromptMode,
          backgroundName: payload.backgroundName ?? "",
          effectNames: payload.effectNames,
          mediaSelectionMode: payload.mediaSelectionMode,
          playerCharacter: payload.playerCharacter,
          readPlayerSpeech: payload.readPlayerSpeech,
          allowPlayerDialogue: payload.allowPlayerDialogue,
          maxDialogItems: payload.maxDialogItems ?? 4,
          maxSpeechChars: payload.maxSpeechChars,
          useCg: payload.useCg,
          useChoice: payload.useChoice,
          useCot: payload.useCot,
          useEffect: payload.useEffect,
          useNarration: payload.useNarration,
          useStat: payload.useStat,
          useTranslation: payload.useTranslation,
          voiceLanguage: payload.voiceLanguage ?? systemConfig.voice_language,
        },
        characters,
        backgrounds,
        systemConfig,
      });
      systemTemplate = generated.system.trimEnd();
    } else {
      systemTemplate = '请严格依据场景设定，用 JSON `{ "dialog": [...] }` 格式驱动交互对话。';
    }
  }

  const effectBlock =
    payload.useEffect !== false && effects.length && payload.effectNames?.length
      ? buildStandaloneEffectCatalogBlock(effects, payload.effectNames, uiLanguage)
      : "";

  const runtimeState = buildRuntimeStateSupplement(
    characters,
    outfits,
    stats,
    userDisplayName,
    payload.playerCharacter,
  );
  const userScenario = (payload.scenario ?? "").trim() || DEFAULT_EMPTY_SCENARIO;
  const jsonReminder = t("closing_json_reminder").trim();

  return [systemTemplate, effectBlock, runtimeState, userScenario, jsonReminder].filter(Boolean).join("\n");
}
