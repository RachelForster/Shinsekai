import { getPlatform } from "../../shared/platform/platform";

export const logsQueryKey = ["logs", "default"] as const;
export const logFilesQueryKey = ["logs", "files"] as const;

export function getDefaultLog() {
  return getPlatform().logs.getDefault();
}

export function listLogFiles() {
  return getPlatform().logs.list();
}

export function exportDiagnosticBundle() {
  return getPlatform().logs.exportDiagnostics();
}

export function importLog(items: File[] | string[]) {
  return getPlatform().logs.import(items);
}

export function readLog(path: string) {
  return getPlatform().logs.import([path]);
}
