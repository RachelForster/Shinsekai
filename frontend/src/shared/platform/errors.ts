import type { MessageKey, TranslateFn } from "../i18n";
import { frontendMessages } from "../i18n/messages";
import { getActiveFrontendLanguage, translateRuntimeMessage } from "../i18n/runtimeLanguage";

export class PlatformRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode?: string,
    readonly errorParams?: Record<string, string | number>,
  ) {
    super(message);
    this.name = "PlatformRequestError";
  }
}

export function platformErrorCode(error: unknown): string | undefined {
  return error instanceof PlatformRequestError ? error.errorCode : undefined;
}

export function formatPlatformError(error: unknown, t?: TranslateFn): string {
  if (error instanceof PlatformRequestError && error.errorCode) {
    const key = `error.${error.errorCode}` as MessageKey;
    const activeLang = getActiveFrontendLanguage();
    const hasKey =
      Object.prototype.hasOwnProperty.call(frontendMessages[activeLang], key) ||
      Object.prototype.hasOwnProperty.call(frontendMessages.zh_CN, key);
    if (hasKey) {
      return t ? t(key, error.errorParams) : translateRuntimeMessage(key, error.errorParams);
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return typeof error === "string" ? error : String(error);
}
