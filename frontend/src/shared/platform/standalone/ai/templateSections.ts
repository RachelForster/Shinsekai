import type { Character } from "../../slices/characterTypes";
import { createStandaloneTemplateTranslator } from "./standaloneTemplateLocales";
import { isSelfPersonaCharacter, isSelfPersonaName } from "./templateResolution";

export type StandaloneTranslator = ReturnType<typeof createStandaloneTemplateTranslator>;

export function withStandaloneSelfPersonaNote(t: StandaloneTranslator, body: string, character: Character): string {
  if (!isSelfPersonaCharacter(character)) {
    return body;
  }
  const note = t("self_persona_identity_note").trim();
  if (!note) {
    return body;
  }
  return body ? `${note}\n${body}` : note;
}

export function formatStandaloneSelfPersonaPrompt(setting: string, t: StandaloneTranslator, name = ""): string {
  const cleaned = setting.trim();
  if (!cleaned) return "";
  const cleanedName = name.trim();
  if (cleanedName && !isSelfPersonaName(cleanedName)) {
    return t("self_persona_block_named", { name: cleanedName, setting: cleaned });
  }
  return t("self_persona_block", { setting: cleaned });
}

export function buildStandalonePlayerSection(options: {
  allowPlayerDialogue: boolean;
  playerCharacter: string;
  playerObj: Character | undefined;
  readPlayerSpeech: boolean;
  selfPersonaName: string;
  selfPersonaSetting: string;
  t: StandaloneTranslator;
  targetVoiceDisplay: string;
  usesVibe: boolean;
}): string {
  const {
    allowPlayerDialogue,
    playerCharacter,
    playerObj,
    readPlayerSpeech,
    selfPersonaName,
    selfPersonaSetting,
    t,
    targetVoiceDisplay,
    usesVibe,
  } = options;
  if (!playerCharacter || !playerObj) {
    return formatStandaloneSelfPersonaPrompt(selfPersonaSetting, t, selfPersonaName);
  }
  const setting = withStandaloneSelfPersonaNote(t, String(playerObj.character_setting ?? "").trim(), playerObj);
  const portraitField = usesVibe ? "vibe" : "sprite";
  const portraitValue = usesVibe ? t("player_portrait_vibe_value") : "01";
  const speechMedia = usesVibe ? '"vibe":""' : '"sprite":"-1"';
  if (allowPlayerDialogue) {
    return t("player_ai_control", {
      name: playerCharacter,
      setting,
      portrait_field: portraitField,
      portrait_value: portraitValue,
    });
  }
  const speechContract = readPlayerSpeech
    ? t("player_speech_contract", {
        name: playerCharacter,
        speech_media: speechMedia,
        target_voice_name: targetVoiceDisplay,
      })
    : t("player_speech_disabled", { name: playerCharacter });
  return t("player_control", {
    name: playerCharacter,
    setting,
    portrait_field: portraitField,
    portrait_value: portraitValue,
    speech_contract: speechContract,
  });
}
