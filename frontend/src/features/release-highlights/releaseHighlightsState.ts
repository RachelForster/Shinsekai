import { releaseHighlights } from "./releases";
import type { ReleaseHighlight } from "./types";

export const FEATURE_HIGHLIGHTS_SEEN_KEY = "shinsekai-feature-highlights-seen";

function getLocalStorage() {
  return typeof window === "undefined" ? undefined : window.localStorage;
}

function normalizeVersion(value: string) {
  return String(value || "")
    .trim()
    .replace(/^[vV]/, "");
}

function parseVersion(value: string) {
  const normalized = normalizeVersion(value);
  if (!/^\d+(?:\.\d+)*$/.test(normalized)) {
    return null;
  }
  return normalized.split(".").map((part) => Number(part));
}

export function compareReleaseVersions(left: string, right: string) {
  const lhs = parseVersion(left);
  const rhs = parseVersion(right);
  if (!lhs || !rhs) {
    return null;
  }
  const width = Math.max(lhs.length, rhs.length);
  for (let index = 0; index < width; index += 1) {
    const difference = (lhs[index] ?? 0) - (rhs[index] ?? 0);
    if (difference !== 0) {
      return difference > 0 ? 1 : -1;
    }
  }
  return 0;
}

export function isReleaseVersion(value: string) {
  return parseVersion(value) !== null;
}

export function readSeenFeatureVersion() {
  try {
    return getLocalStorage()?.getItem(FEATURE_HIGHLIGHTS_SEEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function markFeatureVersionSeen(version: string) {
  try {
    getLocalStorage()?.setItem(FEATURE_HIGHLIGHTS_SEEN_KEY, normalizeVersion(version));
  } catch {
    // Storage may be unavailable in restricted browser contexts.
  }
}

export function getUnseenReleaseHighlights(
  currentVersion: string,
  seenVersion = readSeenFeatureVersion(),
  releases: ReleaseHighlight[] = releaseHighlights,
) {
  if (!isReleaseVersion(currentVersion)) {
    return [];
  }
  return [...releases]
    .filter((release) => {
      const atOrBelowCurrent = compareReleaseVersions(release.version, currentVersion);
      const aboveSeen = seenVersion ? compareReleaseVersions(release.version, seenVersion) : 1;
      return atOrBelowCurrent !== null && atOrBelowCurrent <= 0 && aboveSeen !== null && aboveSeen > 0;
    })
    .sort((left, right) => compareReleaseVersions(left.version, right.version) ?? 0);
}
