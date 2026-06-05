import { getPlatform } from "../../shared/platform/platform";
import type { TemplateGenerateInput, TemplateLaunchSession, TemplateSummary } from "../../shared/platform/types";

export const templatesQueryKey = ["templates"] as const;

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

export type { TemplateSummary };
