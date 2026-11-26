import { tagContents } from "../../../assets/assetText";
import {
  DEFAULT_SPRITE_GROUP,
  LANG_ALIAS_CHINESE_ZH,
  LANG_ALIAS_ENGLISH_ZH,
  LEGACY_TRANSPARENT_BACKGROUND_ALIAS,
  TRANSPARENT_BACKGROUND_NAME,
} from "../../../constants";
import { translateRuntimeMessage } from "../../../i18n/runtimeLanguage";
import { SELF_PERSONA_NAME } from "../../../playerCharacterOptions";
import { PlatformRequestError } from "../../errors";
import type { Character, RelationEdge } from "../../slices/characterTypes";
import type { AppConfig, SystemConfig } from "../../slices/configTypes";
import type {
  Background,
  Effect,
  MediaSelectionMode,
  TemplateGenerateInput,
  TemplateGenerationResult,
} from "../../slices/workspaceTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";

export { SELF_PERSONA_NAME };
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

export function targetVoiceKey(code?: string | null): "ja" | "en" | "zh" | "yue" {
  const raw = String(code ?? "").trim() || "ja";
  const low = raw.toLowerCase();
  if (low === "yue" || low === "yue_hk" || low === "cantonese" || low === "cht" || low === "zh_hk") {
    return "yue";
  }
  if (low.startsWith("en") || low === "english" || low === LANG_ALIAS_ENGLISH_ZH) {
    return "en";
  }
  if (low.startsWith("zh") || low === "chinese" || low === LANG_ALIAS_CHINESE_ZH) {
    return "zh";
  }
  return "ja";
}

export function isUiVoiceSameLanguage(uiLanguage?: string, voiceLanguage?: string): boolean {
  const uiNorm = String(uiLanguage ?? "zh_CN").trim();
  const uiMain = uiNorm.split(/[-_]/)[0].toLowerCase() || "zh";
  const voiceMain = targetVoiceKey(voiceLanguage);
  return uiMain === voiceMain;
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

function spriteGroupOf(group: string | null | undefined): string {
  return String(group ?? "").trim() || DEFAULT_SPRITE_GROUP;
}

function listNonEmptySpriteGroups(character: Character): string[] {
  const sprites = character.sprites ?? [];
  const present = new Set<string>();
  const presentOrder: string[] = [];
  for (const sprite of sprites) {
    const grp = spriteGroupOf(sprite.group);
    if (!present.has(grp)) {
      present.add(grp);
      presentOrder.push(grp);
    }
  }
  const configured = (character.sprite_groups ?? []).map((g) => spriteGroupOf(g));
  const ordered = configured.filter((g) => present.has(g));
  for (const grp of presentOrder) {
    if (!ordered.includes(grp)) ordered.push(grp);
  }
  return ordered;
}

function resolveDefaultSpriteGroup(character: Character): string {
  const present = listNonEmptySpriteGroups(character);
  const configured = String(character.default_sprite_group ?? "").trim();
  if (configured) {
    const norm = spriteGroupOf(configured);
    if (!present.length || present.includes(norm)) {
      return norm;
    }
  }
  if (!present.length || present.includes(DEFAULT_SPRITE_GROUP)) {
    return DEFAULT_SPRITE_GROUP;
  }
  return present[0];
}

function characterSpriteCatalogText(
  character: Character,
  t: ReturnType<typeof createStandaloneTemplateTranslator>,
): string {
  const sprites = character.sprites ?? [];
  const nonEmptyGroups = listNonEmptySpriteGroups(character);
  if (nonEmptyGroups.length < 2) {
    return `${t("sprites_count", { name: character.name, n: sprites.length })}${character.emotion_tags ?? ""}\n\n`;
  }
  const defaultGroup = resolveDefaultSpriteGroup(character);
  const indices: number[] = [];
  sprites.forEach((sprite, idx) => {
    if (spriteGroupOf(sprite.group) === defaultGroup) {
      indices.push(idx);
    }
  });
  const tags = tagContents(character.emotion_tags ?? "", sprites.length);
  const filteredTags = indices.map((idx) => (tags[idx] ? `${idx + 1}:${tags[idx]}` : `${idx + 1}:`)).join(", ");
  return `${t("sprites_count", { name: character.name, n: indices.length })}${filteredTags}\n\n`;
}

function formatSelfPersonaPrompt(setting: string, t: ReturnType<typeof createStandaloneTemplateTranslator>): string {
  const cleaned = setting.trim();
  if (!cleaned) return "";
  return t("self_persona_block", { setting: cleaned });
}

function cleanInlineText(value: unknown): string {
  return String(value ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

function buildRelationSectionText(
  characters: Character[],
  primaryNames: Set<string> | null,
  t: ReturnType<typeof createStandaloneTemplateTranslator>,
): string {
  const selectedKeys = new Set(characters.map((c) => characterNameKey(c.name)));
  const blocks: string[] = [];

  for (const char of characters) {
    if (primaryNames !== null && !primaryNames.has(char.name)) continue;
    const graph = char.relation_graph;
    if (!graph?.edges?.length) continue;

    const filtered: RelationEdge[] = graph.edges
      .filter((edge) => {
        const srcKey = characterNameKey(edge.source);
        const dstKey = characterNameKey(edge.target);
        return (
          (selectedKeys.has(srcKey) || selectedKeys.has(dstKey)) &&
          (edge.content.trim().length > 0 || edge.temperature !== 0)
        );
      })
      .sort((a, b) => {
        const aBoth = selectedKeys.has(characterNameKey(a.source)) && selectedKeys.has(characterNameKey(a.target));
        const bBoth = selectedKeys.has(characterNameKey(b.source)) && selectedKeys.has(characterNameKey(b.target));
        if (aBoth !== bBoth) return aBoth ? -1 : 1;
        if (a.source !== b.source) return a.source.localeCompare(b.source);
        return a.target.localeCompare(b.target);
      });

    if (!filtered.length) continue;
    const heading = t("relations_owner", { name: cleanInlineText(char.name) });
    const lines = filtered.map((edge) => {
      let line = t("relations_edge", {
        source: cleanInlineText(edge.source),
        target: cleanInlineText(edge.target),
        content: cleanInlineText(edge.content),
      });
      if (edge.temperature) {
        line += t("relations_temperature", { temperature: edge.temperature });
      }
      return line;
    });
    blocks.push(`${heading}\n${lines.join("\n")}`);
  }

  if (!blocks.length) return "";
  return `${t("relations_header")}${t("relations_description")}\n${blocks.join("\n\n")}\n\n`;
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

export function buildStandaloneEffectCatalogBlock(
  effects: Effect[],
  selectedNames?: string[] | string,
  uiLanguage?: string,
): string {
  const rawList = Array.isArray(selectedNames)
    ? selectedNames
    : typeof selectedNames === "string"
      ? selectedNames.split(",")
      : [];
  const selectedKeys = new Set(
    rawList
      .map((s) =>
        String(s ?? "")
          .trim()
          .toLowerCase(),
      )
      .filter(Boolean),
  );
  if (!selectedKeys.size || !effects.length) {
    return "";
  }

  const t = createStandaloneTemplateTranslator(uiLanguage);
  const catalog = new Map<string, { label: string; kind: "audio" | "image" | "image_audio" }>();
  const labelOrder: string[] = [];

  for (const effect of effects) {
    const effectName = String(effect.name ?? "").trim();
    if (!effectName || !selectedKeys.has(effectName.toLowerCase())) continue;

    const audioList = effect.audio_list ?? [];
    const audioTags = tagContents(effect.audio_tags ?? "", audioList.length, true);
    for (let i = 0; i < audioList.length; i += 1) {
      if (!audioList[i] || !audioTags[i]?.trim()) continue;
      for (const rawPart of audioTags[i].split(/[,，]/)) {
        const kw = rawPart.trim();
        if (!kw) continue;
        const key = kw.toLowerCase();
        if (!catalog.has(key)) labelOrder.push(key);
        catalog.set(key, { label: catalog.get(key)?.label ?? kw, kind: "audio" });
      }
    }

    const imageList = effect.image_list ?? [];
    const imageAudio = effect.image_audio_list ?? [];
    const imageTags = tagContents(effect.image_tags ?? "", imageList.length, true);
    for (let i = 0; i < imageList.length; i += 1) {
      if (!imageList[i] || !imageTags[i]?.trim()) continue;
      const hasBoundAudio = Boolean(imageAudio[i]?.trim());
      for (const rawPart of imageTags[i].split(/[,，]/)) {
        const kw = rawPart.trim();
        if (!kw) continue;
        const key = kw.toLowerCase();
        if (!catalog.has(key)) labelOrder.push(key);
        catalog.set(key, {
          label: catalog.get(key)?.label ?? kw,
          kind: hasBoundAudio ? "image_audio" : "image",
        });
      }
    }
  }

  if (!labelOrder.length) return "";

  const lines = [t("effects_header").trim()];
  for (const key of labelOrder) {
    const entry = catalog.get(key);
    if (!entry) continue;
    const hasImage = entry.kind === "image" || entry.kind === "image_audio";
    const modes = hasImage ? "before, after" : "before, after, loop, stop";
    const kindLabel = t(`effect_type_${entry.kind}`);
    lines.push(`- ${entry.label} [${kindLabel}; ${modes}]`);
  }
  return `\n${lines.join("\n")}`;
}
