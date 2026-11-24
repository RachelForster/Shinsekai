import { getPlatform } from "../../shared/platform/platform";
import type {
  AppliedUserPromptPreset,
  TemplateGenerateInput,
  TemplateLaunchSession,
  TemplateSummary,
  UserPromptPreset,
  UserPromptPresetLibrary,
} from "../../shared/platform/types";

export const templatesQueryKey = ["templates"] as const;
export const userPromptPresetsQueryKey = ["templates", "presets"] as const;

export function listTemplates() {
  return getPlatform().templates.list();
}

export function saveTemplate(template: TemplateSummary) {
  return getPlatform().templates.save(template);
}

export function generateTemplate(input: TemplateGenerateInput) {
  return getPlatform().templates.generate(input);
}

export function getTemplateSession() {
  return getPlatform().templates.getSession();
}

export function saveTemplateSession(session: TemplateLaunchSession) {
  return getPlatform().templates.saveSession(session);
}

export function getUserPromptPresets() {
  return getPlatform().templates.getPresets();
}

export function saveUserPromptPresets(library: UserPromptPresetLibrary) {
  return getPlatform().templates.savePresets(library);
}

export type { AppliedUserPromptPreset, TemplateSummary, UserPromptPreset, UserPromptPresetLibrary };
