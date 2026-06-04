import type { FileBrowserSnapshot } from "../platform/types";

export type DesktopRuntimeStatus = "checking" | "missing" | "needsAction" | "updating" | "ready" | "error";

export type DesktopRuntimeCandidateKind = "explicit" | "managed" | "managedVenv" | "portable" | "conda" | "path";

export type DesktopRuntimeCandidateStatus =
  | "ready"
  | "missingCoreDeps"
  | "missingOptionalDeps"
  | "unsupportedVersion"
  | "wrongArchitecture"
  | "brokenBridge"
  | "brokenPython";

export type DesktopRuntimeRepairAction =
  | "start"
  | "createManagedVenv"
  | "installRuntimeDeps"
  | "selectDifferentRuntime";

export interface DesktopRuntimeCandidate {
  id: string;
  pythonId?: string | null;
  label: string;
  path: string;
  kind: DesktopRuntimeCandidateKind;
  version?: string | null;
  status: DesktopRuntimeCandidateStatus;
  message?: string | null;
  score: number;
  selected: boolean;
  managed: boolean;
  missingPackages: string[];
  missingImports: string[];
  pythonVersion?: string | null;
  warnings: string[];
  repairActions: DesktopRuntimeRepairAction[];
}

export interface DesktopRuntimeState {
  status: DesktopRuntimeStatus;
  message?: string | null;
  bridgeUrl: string;
  selectedCandidateId?: string | null;
  recommendedAction?: DesktopRuntimeRepairAction | null;
  candidates: DesktopRuntimeCandidate[];
}

export type DesktopRuntimeProgressPhase = "probing" | "installingDeps" | "checkingBridge" | "ready";

export interface DesktopRuntimeProgress {
  phase: DesktopRuntimeProgressPhase;
  candidateId?: string | null;
  source?: string | null;
  downloaded?: number | null;
  total?: number | null;
  speedBytesPerSec?: number | null;
  message?: string | null;
}

export interface DesktopUpdate {
  version: string;
  date?: string | null;
  body?: string | null;
}

export type DesktopUpdateProgressEvent = "started" | "progress" | "finished";

export interface DesktopUpdateProgress {
  event: DesktopUpdateProgressEvent;
  downloaded: number;
  contentLength?: number | null;
}

export type DesktopEventUnlisten = () => void;

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
    __SHINSEKAI_RESTARTING__?: boolean;
    __SHINSEKAI_BRIDGE_RESTARTING__?: boolean;
  }
}

const bridgeRestartFinishedEvent = "shinsekai:bridge-restart-finished";
const desktopUpdateProgressEvent = "shinsekai:update-progress";
const desktopRuntimeProgressEvent = "shinsekai:runtime-progress";

export function isTauriDesktop() {
  if (typeof window === "undefined") {
    return false;
  }
  return (
    Boolean(window.__TAURI_INTERNALS__) ||
    window.location.protocol === "shinsekai:" ||
    window.location.protocol === "tauri:" ||
    window.location.hostname === "tauri.localhost"
  );
}

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(command, args);
}

export function getDesktopRuntimeState() {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_state");
}

export function scanDesktopRuntime() {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_scan");
}

export function startDesktopRuntime(candidateId?: string | null) {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_start", { candidateId });
}

export function selectDesktopRuntime(candidateId: string) {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_select", { candidateId });
}

export function chooseDesktopRuntimePython(path: string) {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_choose_python", { path });
}

export function repairDesktopRuntime(candidateId: string, action: DesktopRuntimeRepairAction) {
  return invokeDesktop<DesktopRuntimeState>("desktop_runtime_repair", { action, candidateId });
}

export function browseDesktopFiles(options?: { path?: string; showHidden?: boolean }) {
  return invokeDesktop<FileBrowserSnapshot>("desktop_files_browse", options ?? {});
}

export function checkDesktopUpdate() {
  return invokeDesktop<DesktopUpdate | null>("desktop_update_check");
}

export async function installDesktopUpdate() {
  markDesktopRestarting();
  console.info("[restart-debug] frontend installDesktopUpdate invoked");
  await writeDesktopRestartDebugLog("installDesktopUpdate invoked");
  try {
    await invokeDesktop<void>("desktop_update_install");
    await writeDesktopRestartDebugLog("desktop_update_install returned; restart should be in progress");
  } catch (error) {
    clearDesktopRestarting();
    await writeDesktopRestartDebugLog(`desktop_update_install rejected: ${desktopRestartErrorMessage(error)}`);
    throw error;
  }
}

export async function onDesktopUpdateProgress(
  listener: (progress: DesktopUpdateProgress) => void,
): Promise<DesktopEventUnlisten> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<DesktopUpdateProgress>(desktopUpdateProgressEvent, (event) => listener(event.payload));
}

export async function onDesktopRuntimeProgress(
  listener: (progress: DesktopRuntimeProgress) => void,
): Promise<DesktopEventUnlisten> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<DesktopRuntimeProgress>(desktopRuntimeProgressEvent, (event) => listener(event.payload));
}

export async function restartDesktopBridge() {
  markDesktopBridgeRestarting();
  console.info("[restart-debug] frontend restartDesktopBridge invoked");
  await writeDesktopRestartDebugLog("restartDesktopBridge invoked");
  try {
    const state = await invokeDesktop<DesktopRuntimeState>("desktop_bridge_restart");
    await writeDesktopRestartDebugLog(`desktop_bridge_restart returned status=${state.status}`);
    return state;
  } catch (error) {
    await writeDesktopRestartDebugLog(`desktop_bridge_restart rejected: ${desktopRestartErrorMessage(error)}`);
    throw error;
  } finally {
    clearDesktopBridgeRestarting();
  }
}

export async function reloadDesktopFrontend() {
  console.info("[restart-debug] frontend reloadDesktopFrontend invoked");
  await writeDesktopRestartDebugLog("reloadDesktopFrontend invoked");
  await invokeDesktop<void>("desktop_frontend_reload");
}

export async function restartDesktopApp() {
  markDesktopRestarting();
  console.info("[restart-debug] frontend restartDesktopApp invoked");
  await writeDesktopRestartDebugLog("restartDesktopApp invoked");
  try {
    await invokeDesktop<void>("desktop_app_restart");
    await writeDesktopRestartDebugLog("desktop_app_restart invoke returned; waiting for old window to exit");
  } catch (error) {
    const message = desktopRestartErrorMessage(error);
    await writeDesktopRestartDebugLog(`desktop_app_restart invoke rejected: ${message}`);
    if (!isExpectedDesktopRestartDisconnect(error)) {
      clearDesktopRestarting();
      throw error;
    }
  }
  return waitForDesktopRestartExit();
}

export async function writeDesktopRestartDebugLog(message: string) {
  if (!isTauriDesktop()) {
    return;
  }
  try {
    await invokeDesktop<void>("desktop_restart_debug_log", { message });
  } catch (error) {
    console.error("[restart-debug] frontend log command failed", error);
  }
}

export function markDesktopRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_RESTARTING__ = true;
  }
}

export function isDesktopRestarting() {
  return typeof window !== "undefined" && window.__SHINSEKAI_RESTARTING__ === true;
}

export function clearDesktopRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_RESTARTING__ = false;
  }
}

export function markDesktopBridgeRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_BRIDGE_RESTARTING__ = true;
  }
}

export function isDesktopBridgeRestarting() {
  return typeof window !== "undefined" && window.__SHINSEKAI_BRIDGE_RESTARTING__ === true;
}

export function clearDesktopBridgeRestarting() {
  if (typeof window !== "undefined") {
    window.__SHINSEKAI_BRIDGE_RESTARTING__ = false;
    window.dispatchEvent(new Event(bridgeRestartFinishedEvent));
  }
}

export function waitForDesktopBridgeRestart(timeoutMs = 15000) {
  if (!isDesktopBridgeRestarting() || typeof window === "undefined") {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    const finish = () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener(bridgeRestartFinishedEvent, finish);
      resolve();
    };
    const timeoutId = window.setTimeout(finish, timeoutMs);
    window.addEventListener(bridgeRestartFinishedEvent, finish, { once: true });
  });
}

export function desktopRestartErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

export function isExpectedDesktopRestartDisconnect(error: unknown) {
  return isDesktopBridgeConnectionError(error) || isDesktopIpcDisconnect(error);
}

export function isDesktopBridgeConnectionError(error: unknown) {
  const message = desktopRestartErrorMessage(error).toLowerCase();
  return (
    message.includes("127.0.0.1") ||
    message.includes("localhost") ||
    message.includes("connection refused") ||
    message.includes("could not connect") ||
    message.includes("connection reset") ||
    message.includes("connection closed") ||
    message.includes("failed to fetch") ||
    message.includes("network")
  );
}

function isDesktopIpcDisconnect(error: unknown) {
  const message = desktopRestartErrorMessage(error).toLowerCase();
  return message.includes("ipc") || message.includes("channel");
}

function waitForDesktopRestartExit(): Promise<never> {
  return new Promise(() => {});
}

export function minimizeDesktopWindow() {
  return invokeDesktop<void>("desktop_window_minimize");
}

export function toggleMaximizeDesktopWindow() {
  return invokeDesktop<void>("desktop_window_toggle_maximize");
}

export function startDesktopWindowDrag() {
  return invokeDesktop<void>("desktop_window_start_drag");
}

export function closeDesktopWindow() {
  return invokeDesktop<void>("desktop_window_close");
}

export function openDesktopExternalUrl(url: string) {
  return invokeDesktop<void>("desktop_open_external_url", { url });
}
