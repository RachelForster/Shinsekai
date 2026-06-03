import { getPlatform } from "../../shared/platform/platform";

export const logsQueryKey = ["logs", "default"] as const;

export function getDefaultLog() {
  return getPlatform().logs.getDefault();
}

export function importLog(items: File[] | string[]) {
  return getPlatform().logs.import(items);
}
