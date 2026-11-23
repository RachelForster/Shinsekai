import { DEFAULT_SPRITE_GROUP } from "../../../constants";
import type { Character } from "../../slices/characterTypes";
import type { CharacterOutfitState, ChatLaunchPayload, ChatStat } from "../../slices/chatTypes";
import type { SystemConfig } from "../../slices/configTypes";
import type { Background, Effect } from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";
import {
  buildStandaloneEffectCatalogBlock,
  generateStandaloneDialogSystemTemplate,
  isSelfPersonaName,
  SELF_PERSONA_NAME,
} from "./templateGenerator";

const SELF_PERSONA_SENTINEL = "__SELF_PERSONA_SETTING_PLACEHOLDER__";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripStandaloneSelfPersonaBlock(text: string): string {
  if (!text) return text;
  let cleaned = text;
  let changed = false;
  for (const locale of ["zh_CN", "en", "ja"] as const) {
    const translator = createStandaloneTemplateTranslator(locale);
    const sample = translator("self_persona_block", { setting: SELF_PERSONA_SENTINEL });
    const markerIndex = sample.indexOf(SELF_PERSONA_SENTINEL);
    if (markerIndex < 0) continue;
    const head = sample.slice(0, markerIndex).trim();
    const tail = sample.slice(markerIndex + SELF_PERSONA_SENTINEL.length).trim();
    if (!head || !tail) continue;
    const pattern = new RegExp(`[ \\t]*${escapeRegExp(head)}[\\s\\S]*?${escapeRegExp(tail)}[ \\t]*(?:\\r?\\n)*`, "g");
    const updated = cleaned.replace(pattern, "\n");
    if (updated !== cleaned) {
      cleaned = updated;
      changed = true;
    }
  }
  if (!changed) return text;
  return cleaned.replace(/\n{3,}/g, "\n\n").replace(/^\n+|\n+$/g, "");
}

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
  t: ReturnType<typeof createStandaloneTemplateTranslator>,
): string {
  const lines: string[] = [];
  const activePlayer = userDisplayName || playerCharacter || "";
  if (activePlayer) {
    lines.push(t("standalone_player_address", { name: activePlayer }));
  }
  if (outfits) {
    const outfitLines: string[] = [];
    for (const char of characters) {
      const state = outfits[char.name];
      if (!state?.activeGroup) continue;
      const defaultGroup = char.default_sprite_group || DEFAULT_SPRITE_GROUP;
      if (state.activeGroup !== defaultGroup || state.locked || (char.sprite_groups?.length ?? 0) > 1) {
        outfitLines.push(`${char.name}: ${state.activeGroup}${state.locked ? t("standalone_outfit_locked") : ""}`);
      }
    }
    if (outfitLines.length) {
      lines.push(t("standalone_outfits_state", { lines: outfitLines.join(t("list_sep_semi")) }));
    }
  }
  if (stats?.length) {
    const statSummary = stats
      .map((s) => `${s.label}: ${s.value}${s.max !== undefined ? `/${s.max}` : ""}`)
      .join(t("list_sep_comma"));
    lines.push(t("standalone_stats_state", { lines: statSummary }));
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

  const hadPersistedSystem = Boolean((payload.system ?? "").trim());
  const selectedCharacterNames = (payload.characters ?? []).filter((name) => {
    const key = name.trim().toLowerCase();
    return Boolean(key) && characters.some((c) => c.name.trim().toLowerCase() === key);
  });
  const effectiveCastNames = selectedCharacterNames.length ? selectedCharacterNames : characters.map((c) => c.name);
  let systemTemplate = (payload.system ?? "").trim();
  if (!systemTemplate) {
    if (characters.length > 0) {
      const generated = generateStandaloneDialogSystemTemplate({
        input: {
          name: payload.templateName || "runtime",
          characters: effectiveCastNames,
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
      systemTemplate = t("standalone_fallback_system_prompt");
    }
  }

  const playerCharacter = (payload.playerCharacter ?? "").trim();
  const hasSelfInCast = effectiveCastNames.some((name) => isSelfPersonaName(name));
  const selfAsPlayer = isSelfPersonaName(playerCharacter);
  const selfAsNpcCast = hasSelfInCast && !selfAsPlayer;
  if (hadPersistedSystem && (hasSelfInCast || selfAsPlayer)) {
    const strippedSystem = stripStandaloneSelfPersonaBlock(systemTemplate);
    if (strippedSystem !== systemTemplate) {
      systemTemplate = strippedSystem;
      if (selfAsNpcCast) {
        const selfChar = characters.find((c) => isSelfPersonaName(c.name));
        const selfSetting = (selfChar?.character_setting ?? "").trim();
        if (selfSetting && !systemTemplate.includes(selfSetting)) {
          const profileHeader = `${t("profile_for", { name: SELF_PERSONA_NAME })}${selfSetting}`;
          systemTemplate = systemTemplate ? `${systemTemplate}\n\n${profileHeader}` : profileHeader;
        }
      }
    }
    if (selfAsNpcCast) {
      const castOverride = t("self_persona_cast_runtime_override").trim();
      if (castOverride && !systemTemplate.includes(castOverride)) {
        systemTemplate = systemTemplate ? `${systemTemplate}\n\n${castOverride}` : castOverride;
      }
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
    t,
  );
  const userScenario = (payload.scenario ?? "").trim() || t("default_empty_scenario");
  const jsonReminder = t("closing_json_reminder").trim();

  return [systemTemplate, effectBlock, runtimeState, userScenario, jsonReminder].filter(Boolean).join("\n");
}
