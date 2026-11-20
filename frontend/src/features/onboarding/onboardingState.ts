import { getRuntimeTarget, isStandaloneRuntimeActive } from "../../shared/platform/runtimeTarget";

const ONBOARDING_SEEN_KEY = "shinsekai-onboarding-seen";
const FIRST_INSTALL_BASELINE_PENDING_KEY = "shinsekai-first-install-baseline-pending";

const ONBOARDING_PATH = "/settings/onboarding";
const TEMPLATE_PATH = "/settings/templates";
const TOY_STAGE_PATH = "/chat";

function readStorage(storage: Storage | undefined, key: string) {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function writeStorage(storage: Storage | undefined, key: string, value: string) {
  try {
    storage?.setItem(key, value);
  } catch {
    // Storage may be unavailable in restricted browser contexts.
  }
}

function getLocalStorage() {
  return typeof window === "undefined" ? undefined : window.localStorage;
}

export function getInitialSettingsPath() {
  if (getRuntimeTarget() === "toy") {
    return TOY_STAGE_PATH;
  }
  if (isStandaloneRuntimeActive()) {
    return TEMPLATE_PATH;
  }
  const localStorage = getLocalStorage();
  if (hasSeenOnboarding()) {
    return TEMPLATE_PATH;
  }

  writeStorage(localStorage, ONBOARDING_SEEN_KEY, "true");
  writeStorage(localStorage, FIRST_INSTALL_BASELINE_PENDING_KEY, "true");
  return ONBOARDING_PATH;
}

export function hasSeenOnboarding() {
  return readStorage(getLocalStorage(), ONBOARDING_SEEN_KEY) === "true";
}

export function hasPendingFirstInstallBaseline() {
  return readStorage(getLocalStorage(), FIRST_INSTALL_BASELINE_PENDING_KEY) === "true";
}

export function clearPendingFirstInstallBaseline() {
  try {
    getLocalStorage()?.removeItem(FIRST_INSTALL_BASELINE_PENDING_KEY);
  } catch {
    // Storage may be unavailable in restricted browser contexts.
  }
}
