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
  DEFAULT_EMPTY_SCENARIO,
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
  TRANSPARENT_BG,
  characterNameKey,
  composeTemplateContent,
  findCharacterByName,
  findSelfPersona,
  isSelfPersonaCharacter,
  isSelfPersonaId,
  isSelfPersonaName,
  isTransparentBackground,
  isUiVoiceSameLanguage,
  normalizeMediaSelectionMode,
  resolvePlayerCharacter,
  resolveTemplateCharacters,
  targetVoiceKey,
} from "./templateResolution";
import { buildStandalonePlayerSection, withStandaloneSelfPersonaNote } from "./templateSections";
import { isUiVoiceSameLanguage as isUiVoiceSameTarget, resolveCastVoiceTarget } from "./voiceLanguage";

export {
  DEFAULT_EMPTY_SCENARIO,
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
  TRANSPARENT_BG,
  buildStandaloneEffectCatalogBlock,
  characterNameKey,
  composeTemplateContent,
  findCharacterByName,
  findSelfPersona,
  isSelfPersonaCharacter,
  isSelfPersonaId,
  isSelfPersonaName,
  isTransparentBackground,
  isUiVoiceSameLanguage,
  normalizeMediaSelectionMode,
  resolvePlayerCharacter,
  resolveTemplateCharacters,
  targetVoiceKey,
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
  if (!playerObj && (isSelfPersonaName(playerCharacter) || isSelfPersonaId(playerCharacter))) {
    playerObj = findSelfPersona(allCharacters);
  }
  if (!playerObj && playerCharacter) {
    const candidate = findCharacterByName(allCharacters, playerCharacter);
    if (candidate && isSelfPersonaCharacter(candidate)) {
      playerObj = candidate;
    }
  }

  if (playerObj && !allowPlayerDialogue) {
    const playerIsSelf = isSelfPersonaCharacter(playerObj);
    const playerKey = characterNameKey(playerCharacter);
    cast = cast.filter((c) => (playerIsSelf ? !isSelfPersonaCharacter(c) : characterNameKey(c.name) !== playerKey));
  }
  if (!cast.length && !playerObj) {
    throw new PlatformRequestError(t("err_no_characters"), 400, "no_valid_characters");
  }

  let selfPersonaSetting = "";
  let selfPersonaName = "";
  if (!playerCharacter && !playerObj && !cast.some((c) => isSelfPersonaCharacter(c))) {
    const selfChar = findSelfPersona(allCharacters);
    if (selfChar) {
      selfPersonaSetting = (selfChar.character_setting ?? "").trim();
      selfPersonaName = (selfChar.name ?? "").trim();
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
    if (setting || isSelfPersonaCharacter(char)) {
      const content = withStandaloneSelfPersonaNote(t, setting, char);
      parts.push(`${t("profile_for", { name: char.name })}${content}\n\n`);
    }
  }

  if (supportingCharacters.length) {
    parts.push(t("brief_header"));
    for (const char of supportingCharacters) {
      const brief = String(char.character_brief ?? "").trim() || String(char.character_setting ?? "");
      if (brief || isSelfPersonaCharacter(char)) {
        const content = withStandaloneSelfPersonaNote(t, brief, char);
        parts.push(`${t("brief_for", { name: char.name })}${content}\n\n`);
      }
    }
  }

  // 4. Player section
  const playerSection = buildStandalonePlayerSection({
    allowPlayerDialogue,
    playerCharacter,
    playerObj,
    readPlayerSpeech,
    selfPersonaName,
    selfPersonaSetting,
    t,
    targetVoiceDisplay,
    usesVibe,
  });
  if (playerSection) {
    parts.push(playerSection);
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
