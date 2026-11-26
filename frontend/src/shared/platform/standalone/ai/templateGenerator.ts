import { LEGACY_TRANSPARENT_BACKGROUND_ALIAS, TRANSPARENT_BACKGROUND_NAME } from "../../../constants";
import { translateRuntimeMessage } from "../../../i18n/runtimeLanguage";
import { SELF_PERSONA_NAME } from "../../../playerCharacterOptions";
import { PlatformRequestError } from "../../errors";
import type { Character } from "../../slices/characterTypes";
import type { AppConfig, SystemConfig } from "../../slices/configTypes";
import type {
  Background,
  MediaSelectionMode,
  TemplateGenerateInput,
  TemplateGenerationResult,
} from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";
import {
  buildRelationSectionText,
  buildStandaloneEffectCatalogBlock,
  characterSpriteCatalogText,
} from "./templateCatalogSections";
import {
  isUiVoiceSameLanguage as isUiVoiceSameTarget,
  resolveCastVoiceTarget,
  targetVoiceKey as resolveVoiceTargetKey,
  type VoiceTargetKey,
} from "./voiceLanguage";

export { buildStandaloneEffectCatalogBlock, SELF_PERSONA_NAME };
export const TRANSPARENT_BG = TRANSPARENT_BACKGROUND_NAME;
const TRANSPARENT_BG_ALIAS = LEGACY_TRANSPARENT_BACKGROUND_ALIAS;
export const DEFAULT_EMPTY_SCENARIO = createStandaloneTemplateTranslator("zh_CN")("default_empty_scenario");

const COT_TOKEN = "COT";
const CHOICE_TOKEN = "CHOICE";
const STAT_TOKEN = "STAT";
const SCENE_TOKEN = "SCENE";
const BGM_TOKEN = "bgm";
const CG_TOKEN = "CG";

export function characterNameKey(name: string): string {
  return name.trim().toLowerCase();
}

export function isSelfPersonaName(name: string | undefined | null): boolean {
  return characterNameKey(String(name ?? "")) === SELF_PERSONA_NAME;
}

export function isTransparentBackground(name?: string | null): boolean {
  const clean = String(name ?? "").trim();
  return !clean || clean === TRANSPARENT_BG || clean === TRANSPARENT_BG_ALIAS;
}

export function normalizeMediaSelectionMode(mode: unknown): MediaSelectionMode {
  return String(mode ?? "")
    .trim()
    .toLowerCase() === "semantic"
    ? "semantic"
    : "indexed";
}

export function targetVoiceKey(code?: string | null): VoiceTargetKey | "auto" {
  return resolveVoiceTargetKey(code);
}

export function isUiVoiceSameLanguage(uiLanguage?: string, voiceLanguage?: string): boolean {
  return isUiVoiceSameTarget(uiLanguage, resolveVoiceTargetKey(voiceLanguage || "ja"));
}

export function composeTemplateContent(scenario: string, system: string): string {
  return [scenario.trim(), system.trim()].filter(Boolean).join("\n\n");
}

function findCharacterByName(characters: Character[], rawName: string): Character | undefined {
  const key = characterNameKey(rawName);
  if (!key) return undefined;
  return characters.find((c) => characterNameKey(c.name) === key);
}

export function resolveTemplateCharacters(selectedNames: string[], allCharacters: Character[]): Character[] {
  const seenKeys = new Set<string>();
  const resolved: Character[] = [];
  for (const raw of selectedNames) {
    const clean = String(raw ?? "").trim();
    if (!clean) continue;
    const reqKey = characterNameKey(clean);
    if (seenKeys.has(reqKey)) continue;
    seenKeys.add(reqKey);

    const found = findCharacterByName(allCharacters, clean);
    if (!found) continue;
    const canonKey = characterNameKey(found.name);
    if (resolved.some((c) => characterNameKey(c.name) === canonKey)) continue;
    resolved.push(found);
  }
  return resolved;
}

export function resolvePlayerCharacter(
  allCharacters: Character[],
  resolvedCastNames: string[],
  rawPlayerName: unknown,
  uiLanguage?: string,
): string {
  const name = String(rawPlayerName ?? "").trim();
  if (!name) return "";
  const character = findCharacterByName(allCharacters, name);
  if (!character) {
    throw new Error(translateRuntimeMessage("plat.standalone.playerMustBeValid", undefined, uiLanguage));
  }
  const castKeys = new Set(resolvedCastNames.map((n) => characterNameKey(n)));
  if (!isSelfPersonaName(character.name) && !castKeys.has(characterNameKey(character.name))) {
    throw new Error(translateRuntimeMessage("plat.standalone.playerMustBeValid", undefined, uiLanguage));
  }
  return character.name;
}

function formatSelfPersonaPrompt(setting: string, t: ReturnType<typeof createStandaloneTemplateTranslator>): string {
  const cleaned = setting.trim();
  if (!cleaned) return "";
  return t("self_persona_block", { setting: cleaned });
}

export interface GenerateTemplateOptions {
  input: TemplateGenerateInput;
  characters: Character[];
  backgrounds: Background[];
  systemConfig: Partial<SystemConfig>;
}

export function generateStandaloneDialogSystemTemplate(options: GenerateTemplateOptions): {
  system: string;
  resolvedCharacters: string[];
  playerCharacter: string;
  readPlayerSpeech: boolean;
  allowPlayerDialogue: boolean;
  mediaSelectionMode: MediaSelectionMode;
} {
  const { input, characters: allCharacters, backgrounds, systemConfig } = options;
  const uiLanguage = systemConfig.ui_language || "zh_CN";
  const t = createStandaloneTemplateTranslator(uiLanguage);

  const selectedList = Array.isArray(input.characters) ? input.characters : [];
  let cast = resolveTemplateCharacters(selectedList, allCharacters);
  const resolvedNames = cast.map((c) => c.name);
  if (!cast.length) {
    throw new PlatformRequestError(t("err_no_characters"), 400, "no_valid_characters");
  }

  const playerCharacter = resolvePlayerCharacter(allCharacters, resolvedNames, input.playerCharacter, uiLanguage);
  const allowPlayerDialogue = input.allowPlayerDialogue !== false;
  const readPlayerSpeech = Boolean(playerCharacter && input.readPlayerSpeech);

  let playerObj = playerCharacter ? findCharacterByName(cast, playerCharacter) : undefined;
  if (!playerObj && isSelfPersonaName(playerCharacter)) {
    const candidate = findCharacterByName(allCharacters, SELF_PERSONA_NAME);
    if (candidate && isSelfPersonaName(candidate.name)) {
      playerObj = candidate;
    }
  }

  if (playerObj && !allowPlayerDialogue) {
    cast = cast.filter((c) => characterNameKey(c.name) !== characterNameKey(playerCharacter));
  }
  if (!cast.length && !playerObj) {
    throw new PlatformRequestError(t("err_no_characters"), 400, "no_valid_characters");
  }

  let selfPersonaSetting = "";
  if (!playerCharacter && !playerObj && !cast.some((c) => isSelfPersonaName(c.name))) {
    const selfChar = findCharacterByName(allCharacters, SELF_PERSONA_NAME);
    if (selfChar && isSelfPersonaName(selfChar.name)) {
      selfPersonaSetting = (selfChar.character_setting ?? "").trim();
    }
  }

  const promptMode = String(input.characterPromptMode ?? "")
    .trim()
    .toLowerCase();
  let primaryNamesSet: Set<string> | null = null;
  if (promptMode === "compact") {
    const primaryCandidates = resolveTemplateCharacters(input.primaryCharacters ?? [], allCharacters).map(
      (c) => c.name,
    );
    if (playerCharacter && !primaryCandidates.includes(playerCharacter)) {
      primaryCandidates.push(playerCharacter);
    }
    const resolvedKeys = new Set(resolvedNames.map((n) => characterNameKey(n)));
    primaryNamesSet = new Set(primaryCandidates.filter((n) => resolvedKeys.has(characterNameKey(n))));
  }

  const mediaSelectionMode = normalizeMediaSelectionMode(input.mediaSelectionMode);
  const usesVibe = mediaSelectionMode === "semantic";
  const usesFullSpriteIds = cast.some((c) => (c.sprites?.length ?? 0) > 99);

  const bgName = String(input.backgroundName ?? "").trim();
  const hasRealBackground = Boolean(bgName) && !isTransparentBackground(bgName);
  const background = hasRealBackground
    ? backgrounds.find((b) => characterNameKey(b.name) === characterNameKey(bgName))
    : undefined;

  const voiceLanguage = String(input.voiceLanguage ?? systemConfig.voice_language ?? "ja").trim();
  const voiceCast =
    playerObj && readPlayerSpeech && !cast.some((c) => characterNameKey(c.name) === characterNameKey(playerCharacter))
      ? [...cast, playerObj]
      : cast;
  const castVoice = resolveCastVoiceTarget(voiceLanguage, voiceCast, uiLanguage);
  const targetVoiceDisplay =
    castVoice.target === "auto"
      ? castVoice.perChar.length
        ? t("voice_target_auto_map", {
            base: t("voice_target_auto"),
            mapping: castVoice.perChar
              .map((item) => `${item.name}:${t(`voice_target_${item.key}`)}`)
              .join(t("name_sep")),
          })
        : t("voice_target_auto")
      : t(`voice_target_${castVoice.target}`);
  const useLlmTranslation = Boolean(input.useTranslation && !isUiVoiceSameTarget(uiLanguage, castVoice.target));
  const useEffect = input.useEffect !== false;
  const useCg = Boolean(input.useCg);
  const useCot = Boolean(input.useCot);
  const useChoice = input.useChoice !== false;
  const useNarration = input.useNarration !== false;
  const useStat = input.useStat !== false;
  const maxSpeechChars = Math.max(0, Number(input.maxSpeechChars ?? 0) || 0);
  const maxDialogItems = Math.max(0, Number(input.maxDialogItems ?? 0) || 0);

  const names = cast.map((c) => c.name).join(t("name_sep"));

  // 1. Preamble
  const parts: string[] = [t("preamble", { names })];

  // 2. JSON Schema section
  const jsonExampleRaw = JSON.stringify(t("json_speech_example"));
  const jsonExample = jsonExampleRaw.slice(1, -1);
  const headKey = usesVibe ? "json_vibe_head_top" : usesFullSpriteIds ? "json_full_sprite_head_top" : "json_head_top";
  parts.push(t(headKey));
  parts.push(t("json_speech_line", { example: jsonExample }));
  if (useEffect) {
    parts.push(t("json_line_effect"));
  }
  if (useLlmTranslation) {
    parts.push(t("json_line_trans", { target_voice_name: targetVoiceDisplay }));
  }
  parts.push(t("json_foot"));

  // 3. Character sprites, profiles, briefs
  const primaryCharacters = primaryNamesSet === null ? cast : cast.filter((c) => primaryNamesSet!.has(c.name));
  const supportingCharacters = primaryNamesSet === null ? [] : cast.filter((c) => !primaryNamesSet!.has(c.name));

  if (!usesVibe && cast.length) {
    parts.push(t("sprites_header"));
    for (const char of cast) {
      parts.push(characterSpriteCatalogText(char, t));
    }
  }

  parts.push(t("profile_header"));
  for (const char of primaryCharacters) {
    const setting = String(char.character_setting ?? "");
    if (setting) {
      parts.push(`${t("profile_for", { name: char.name })}${setting}\n\n`);
    }
  }

  if (supportingCharacters.length) {
    parts.push(t("brief_header"));
    for (const char of supportingCharacters) {
      const brief = String(char.character_brief ?? "").trim() || String(char.character_setting ?? "");
      if (brief) {
        parts.push(`${t("brief_for", { name: char.name })}${brief}\n\n`);
      }
    }
  }

  // 4. Player section
  if (!playerCharacter || !playerObj) {
    const persona = formatSelfPersonaPrompt(selfPersonaSetting, t);
    if (persona) parts.push(persona);
  } else {
    const setting = String(playerObj.character_setting ?? "").trim();
    const portraitField = usesVibe ? "vibe" : "sprite";
    const portraitValue = usesVibe ? t("player_portrait_vibe_value") : "01";
    const speechMedia = usesVibe ? '"vibe":""' : '"sprite":"-1"';
    if (allowPlayerDialogue) {
      parts.push(
        t("player_ai_control", {
          name: playerCharacter,
          setting,
          portrait_field: portraitField,
          portrait_value: portraitValue,
        }),
      );
    } else {
      const speechContract = readPlayerSpeech
        ? t("player_speech_contract", {
            name: playerCharacter,
            speech_media: speechMedia,
            target_voice_name: targetVoiceDisplay,
          })
        : t("player_speech_disabled", { name: playerCharacter });
      parts.push(
        t("player_control", {
          name: playerCharacter,
          setting,
          portrait_field: portraitField,
          portrait_value: portraitValue,
          speech_contract: speechContract,
        }),
      );
    }
  }

  // 5. Relations section
  const relText = buildRelationSectionText(cast, primaryNamesSet, t);
  if (relText) {
    parts.push(relText);
  }

  // 6. Background scenes & BGM section
  if (!usesVibe && hasRealBackground && background) {
    if (background.sprites?.length) {
      parts.push(
        `${t("scene_block_header")}${t("scene_count", { n: background.sprites.length })}${background.bg_tags ?? ""}\n\n`,
      );
    }
    if (background.bgm_list?.length) {
      parts.push(
        `${t("bgm_block_header")}${t("bgm_count", { n: background.bgm_list.length })}${background.bgm_tags ?? ""}\n\n`,
      );
    }
  }

  // 7. Requirements section
  const narr = t("narr_token");
  const fixedRoles = [useNarration ? narr : "", useChoice ? CHOICE_TOKEN : "", useStat ? STAT_TOKEN : ""]
    .filter(Boolean)
    .join("、");

  const ruleEntries: Array<{ enabled: boolean; text: string }> = [
    { enabled: useCot, text: t("r_cot", { cot: COT_TOKEN }) },
    { enabled: true, text: t("r_format") },
    {
      enabled: true,
      text: t("r_cname", {
        names,
        cot_part: useCot ? `${COT_TOKEN},` : "",
        fixed_roles: fixedRoles ? ` ${fixedRoles}` : "",
        opt_scene: hasRealBackground ? `, ${SCENE_TOKEN}` : "",
        opt_bgm: hasRealBackground ? `, ${BGM_TOKEN}` : "",
        opt_cg: useCg ? `, ${CG_TOKEN}` : "",
      }),
    },
    usesVibe
      ? { enabled: true, text: t("r_vibe") }
      : { enabled: true, text: t(usesFullSpriteIds ? "r_full_sprite" : "r_sprite") },
    {
      enabled: true,
      text: t(usesVibe ? "r_non_vibe" : "r_non_sprite", { fixed_roles_non_sprite: fixedRoles }),
    },
    { enabled: hasRealBackground, text: t(usesVibe ? "r_scene_vibe" : "r_scene", { scn: SCENE_TOKEN }) },
    { enabled: hasRealBackground, text: t(usesVibe ? "r_bgm_vibe" : "r_bgm", { bgm_t: BGM_TOKEN }) },
    { enabled: true, text: t("r_speech", { speech_lang_name: t("speech_lang_name") }) },
    { enabled: true, text: t("r_array") },
    { enabled: maxSpeechChars > 0, text: t("r_speech_max_chars", { n: maxSpeechChars }) },
    { enabled: maxDialogItems > 0, text: t("r_dialog_max_items", { n: maxDialogItems }) },
    { enabled: useNarration, text: t("r_narration", { narr }) },
    { enabled: useChoice, text: t("r_choice_pos", { choice: CHOICE_TOKEN }) },
    { enabled: useChoice, text: t("r_choice_format", { choice: CHOICE_TOKEN }) },
    { enabled: useChoice, text: t("r_choice_balance") },
    { enabled: useStat, text: t("r_stats", { stat: STAT_TOKEN }) },
    { enabled: useCg, text: t("r_cg", { cg: CG_TOKEN }) },
    { enabled: useLlmTranslation, text: t("r_translate", { target_voice_name: targetVoiceDisplay }) },
    { enabled: useEffect, text: t("r_effect") },
  ];

  parts.push(t("requirements_header"));
  for (const rule of ruleEntries) {
    if (rule.enabled) {
      parts.push(`- ${rule.text}\n`);
    }
  }
  parts.push(t("closing", { extra: hasRealBackground ? t("closing_extra_bgm") : "" }));
  parts.push(`${t("closing_json_reminder")}\n`);

  return {
    system: parts.join(""),
    resolvedCharacters: resolvedNames,
    playerCharacter,
    readPlayerSpeech,
    allowPlayerDialogue,
    mediaSelectionMode,
  };
}

export function generateStandaloneTemplateSummary(
  input: TemplateGenerateInput,
  config: Pick<AppConfig, "characters" | "background_list" | "system_config">,
): TemplateGenerationResult {
  const result = generateStandaloneDialogSystemTemplate({
    input,
    characters: config.characters ?? [],
    backgrounds: config.background_list ?? [],
    systemConfig: config.system_config ?? {},
  });
  const scenario = String(input.scenario ?? "");
  const name = String(input.name ?? "").trim() || "generated";
  return {
    content: composeTemplateContent(scenario, result.system),
    generationMessage: "",
    id: "",
    name,
    path: "",
    mediaSelectionMode: result.mediaSelectionMode,
    scenario,
    system: result.system,
    playerCharacter: result.playerCharacter,
    readPlayerSpeech: result.readPlayerSpeech,
    allowPlayerDialogue: result.allowPlayerDialogue,
    resolvedCharacters: result.resolvedCharacters,
    updatedAt: "",
  };
}
