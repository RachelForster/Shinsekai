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
  characterNameKey,
  composeTemplateContent,
  DEFAULT_EMPTY_SCENARIO,
  findCharacterByName,
  findCharacterByPromptName,
  isSelfPersonaName,
  isTransparentBackground,
  isUiVoiceSameLanguage,
  normalizeMediaSelectionMode,
  resolveCharacterPromptName,
  resolvePlayerCharacter,
  resolveTemplateCharacters,
  SELF_PERSONA_NAME,
  targetVoiceKey,
  TRANSPARENT_BG,
} from "./templateResolution";
import {
  buildRelationSectionText,
  buildStandaloneEffectCatalogBlock,
  characterSpriteCatalogText,
  formatSelfPersonaPrompt,
} from "./templateSections";

export {
  buildStandaloneEffectCatalogBlock,
  characterNameKey,
  composeTemplateContent,
  DEFAULT_EMPTY_SCENARIO,
  findCharacterByName,
  findCharacterByPromptName,
  isSelfPersonaName,
  isTransparentBackground,
  isUiVoiceSameLanguage,
  normalizeMediaSelectionMode,
  resolveCharacterPromptName,
  resolvePlayerCharacter,
  resolveTemplateCharacters,
  SELF_PERSONA_NAME,
  targetVoiceKey,
  TRANSPARENT_BG,
};

const COT_TOKEN = "COT";
const CHOICE_TOKEN = "CHOICE";
const STAT_TOKEN = "STAT";
const SCENE_TOKEN = "SCENE";
const BGM_TOKEN = "bgm";
const CG_TOKEN = "CG";

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

  const selfChar = findCharacterByName(allCharacters, SELF_PERSONA_NAME);
  const hasSelfInCast = cast.some((c) => isSelfPersonaName(c.name));
  const selfPersonaSetting =
    !playerCharacter && !playerObj && !hasSelfInCast && selfChar && isSelfPersonaName(selfChar.name)
      ? (selfChar.character_setting ?? "").trim()
      : "";

  const collidingNames = [...cast.map((c) => c.name), ...(playerCharacter ? [playerCharacter] : [])];
  const selfPromptName = selfChar ? resolveCharacterPromptName(selfChar, collidingNames) : "";
  const selfDisplayPromptName = selfPromptName && !isSelfPersonaName(selfPromptName) ? selfPromptName : "";

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
  const targetVoiceDisplay = t(`voice_target_${targetVoiceKey(voiceLanguage)}`);
  const useLlmTranslation = Boolean(input.useTranslation && !isUiVoiceSameLanguage(uiLanguage, voiceLanguage));
  const useEffect = input.useEffect !== false;
  const useCg = Boolean(input.useCg);
  const useCot = Boolean(input.useCot);
  const useChoice = input.useChoice !== false;
  const useNarration = input.useNarration !== false;
  const useStat = input.useStat !== false;
  const maxSpeechChars = Math.max(0, Number(input.maxSpeechChars ?? 0) || 0);
  const maxDialogItems = Math.max(0, Number(input.maxDialogItems ?? 0) || 0);

  const names = cast.map((c) => resolveCharacterPromptName(c, collidingNames)).join(t("name_sep"));

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
      parts.push(characterSpriteCatalogText(char, t, collidingNames));
    }
  }

  parts.push(t("profile_header"));
  for (const char of primaryCharacters) {
    const promptName = resolveCharacterPromptName(char, collidingNames);
    const setting = String(char.character_setting ?? "");
    const isSelf = isSelfPersonaName(char.name);
    if (setting || isSelf) {
      const note = isSelf ? t("self_persona_identity_note") : "";
      const body = isSelf ? (setting ? `${note}\n${setting}` : note) : setting;
      parts.push(`${t("profile_for", { name: promptName })}${body}\n\n`);
    }
  }

  if (supportingCharacters.length) {
    parts.push(t("brief_header"));
    for (const char of supportingCharacters) {
      const promptName = resolveCharacterPromptName(char, collidingNames);
      const brief = String(char.character_brief ?? "").trim() || String(char.character_setting ?? "");
      const isSelf = isSelfPersonaName(char.name);
      if (brief || isSelf) {
        const note = isSelf ? t("self_persona_identity_note") : "";
        const body = isSelf ? (brief ? `${note}\n${brief}` : note) : brief;
        parts.push(`${t("brief_for", { name: promptName })}${body}\n\n`);
      }
    }
  }

  // 4. Player section
  if (!playerCharacter || !playerObj) {
    if (!hasSelfInCast) {
      const persona = formatSelfPersonaPrompt(selfPersonaSetting, t, selfDisplayPromptName);
      if (persona) parts.push(persona);
    }
  } else {
    const playerPromptName = resolveCharacterPromptName(playerObj, collidingNames, playerCharacter);
    const rawSetting = String(playerObj.character_setting ?? "").trim();
    const setting = isSelfPersonaName(playerCharacter)
      ? rawSetting
        ? `${t("self_persona_identity_note")}\n${rawSetting}`
        : t("self_persona_identity_note")
      : rawSetting;
    const portraitField = usesVibe ? "vibe" : "sprite";
    const portraitValue = usesVibe ? t("player_portrait_vibe_value") : "01";
    const speechMedia = usesVibe ? '"vibe":""' : '"sprite":"-1"';
    if (allowPlayerDialogue) {
      parts.push(
        t("player_ai_control", {
          name: playerPromptName,
          setting,
          portrait_field: portraitField,
          portrait_value: portraitValue,
        }),
      );
    } else {
      const speechContract = readPlayerSpeech
        ? t("player_speech_contract", {
            name: playerPromptName,
            speech_media: speechMedia,
            target_voice_name: targetVoiceDisplay,
          })
        : t("player_speech_disabled", { name: playerPromptName });
      parts.push(
        t("player_control", {
          name: playerPromptName,
          setting,
          portrait_field: portraitField,
          portrait_value: portraitValue,
          speech_contract: speechContract,
        }),
      );
    }
  }

  // 5. Relations section
  const relText = buildRelationSectionText(cast, primaryNamesSet, t, selfDisplayPromptName);
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
