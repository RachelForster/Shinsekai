import { enMessages } from "./messages/en";
import { jaMessages } from "./messages/ja";
import { zhCNMessages } from "./messages/zh_CN";

export type FrontendLanguage = "zh_CN" | "en" | "ja";

export type MessageKey = keyof typeof zhCNMessages;

export const frontendMessages: Record<FrontendLanguage, Record<MessageKey, string>> = {
  en: enMessages,
  ja: jaMessages,
  zh_CN: zhCNMessages,
};
