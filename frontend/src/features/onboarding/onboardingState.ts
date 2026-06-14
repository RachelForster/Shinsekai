const ONBOARDING_SEEN_KEY = "shinsekai-onboarding-seen";

const ONBOARDING_PATH = "/settings/onboarding";
const TEMPLATE_PATH = "/settings/templates";

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
  const localStorage = getLocalStorage();
  const hasSeenOnboarding = readStorage(localStorage, ONBOARDING_SEEN_KEY) === "true";
  if (hasSeenOnboarding) {
    return TEMPLATE_PATH;
  }

  writeStorage(localStorage, ONBOARDING_SEEN_KEY, "true");
  return ONBOARDING_PATH;
}
