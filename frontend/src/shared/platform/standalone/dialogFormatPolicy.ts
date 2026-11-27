import type { ChatLaunchPayload } from "../slices/chatTypes";
import type {
  DialogFormatOption,
  DialogOutputFormatId,
  TemplateLaunchSession,
  TemplateSummary,
} from "../slices/workspaceTypes";

export const STANDALONE_DIALOG_FORMAT_ID: DialogOutputFormatId = "json_v1";

export function listStandaloneDialogFormats(): DialogFormatOption[] {
  return [{ id: STANDALONE_DIALOG_FORMAT_ID, label: "JSON", builtin: true }];
}

export function normalizeStandaloneTemplate(template: TemplateSummary): TemplateSummary {
  return {
    ...template,
    outputFormat: STANDALONE_DIALOG_FORMAT_ID,
  };
}

export function normalizeStandaloneTemplateSession(session: TemplateLaunchSession): TemplateLaunchSession {
  return {
    ...session,
    outputFormat: STANDALONE_DIALOG_FORMAT_ID,
  };
}

export function normalizeStandaloneChatLaunchPayload(payload: ChatLaunchPayload): ChatLaunchPayload {
  return {
    ...payload,
    outputFormat: STANDALONE_DIALOG_FORMAT_ID,
    ...(payload.editorSession ? { editorSession: normalizeStandaloneTemplateSession(payload.editorSession) } : {}),
  };
}
