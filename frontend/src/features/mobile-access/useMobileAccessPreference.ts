import { useSyncExternalStore } from "react";

export const mobileAccessPreferenceKey = "shinsekai.chat.mobile-access.v1";
const changedEvent = "shinsekai:mobile-access-preference";
let transientPreference: boolean | undefined;

function readPreference(): boolean {
  if (transientPreference !== undefined) return transientPreference;
  try {
    return localStorage.getItem(mobileAccessPreferenceKey) === "true";
  } catch {
    return false;
  }
}

export function setMobileAccessPreference(enabled: boolean): void {
  try {
    localStorage.setItem(mobileAccessPreferenceKey, String(enabled));
    transientPreference = undefined;
  } catch {
    // Storage may be disabled; the current window must still be usable.
    transientPreference = enabled;
  }
  window.dispatchEvent(new Event(changedEvent));
}

function subscribe(notify: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === mobileAccessPreferenceKey || event.key === null) {
      transientPreference = undefined;
      notify();
    }
  };
  window.addEventListener(changedEvent, notify);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(changedEvent, notify);
    window.removeEventListener("storage", onStorage);
  };
}

/** One device-level launch preference, shared by creation and resume entry points. */
export function useMobileAccessPreference() {
  return [useSyncExternalStore(subscribe, readPreference, () => false), setMobileAccessPreference] as const;
}
