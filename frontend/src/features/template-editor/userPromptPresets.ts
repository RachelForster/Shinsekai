import type { AppliedUserPromptPreset, UserPromptPreset, UserPromptPresetLibrary } from "../../shared/platform/types";

export interface ResolvedUserPromptPreset {
  id: string;
  name: string;
  group: string;
  color?: string;
  content: string;
  isDeleted: boolean;
}

export const PRESET_COLOR_SWATCHES = ["#5b8def", "#e879a8", "#46b98b", "#f0a44b", "#9b7ef5", "#4eb8d6"] as const;

export function createUserPromptPresetId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `preset-${crypto.randomUUID()}`;
  }
  return `preset-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function normalizeUserPromptPresetLibrary(
  raw?: Partial<UserPromptPresetLibrary> | null,
): UserPromptPresetLibrary {
  const groups: string[] = [];
  const seenGroups = new Set<string>();
  for (const item of raw?.groups ?? []) {
    const group = String(item ?? "")
      .trim()
      .slice(0, 64);
    if (group && !seenGroups.has(group)) {
      seenGroups.add(group);
      groups.push(group);
    }
  }

  const presets: UserPromptPreset[] = [];
  const seenIds = new Set<string>();
  for (const entry of raw?.presets ?? []) {
    const id = String(entry?.id ?? "")
      .trim()
      .slice(0, 128);
    const name = String(entry?.name ?? "")
      .trim()
      .slice(0, 64);
    if (!id || !name || seenIds.has(id)) {
      continue;
    }
    seenIds.add(id);
    const group = String(entry?.group ?? "")
      .trim()
      .slice(0, 64);
    if (group && !seenGroups.has(group)) {
      seenGroups.add(group);
      groups.push(group);
    }
    const color = String(entry?.color ?? "")
      .trim()
      .slice(0, 32);
    const content = String(entry?.content ?? "").replace(/\r\n/g, "\n");
    presets.push({
      id,
      name,
      group,
      ...(color ? { color } : {}),
      content,
    });
  }

  return { groups, presets };
}

export function resolveSelectedPresets(
  selectedIds: readonly string[],
  library: UserPromptPresetLibrary,
  snapshotFallback: readonly AppliedUserPromptPreset[] = [],
  options?: { libraryLoaded?: boolean },
): ResolvedUserPromptPreset[] {
  const libraryLoaded = options?.libraryLoaded ?? true;
  const byId = new Map(library.presets.map((preset) => [preset.id, preset]));
  const fallbackById = new Map(snapshotFallback.map((preset) => [preset.id, preset]));
  const resolved: ResolvedUserPromptPreset[] = [];
  const seen = new Set<string>();
  for (const rawId of selectedIds) {
    const id = String(rawId ?? "").trim();
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    const live = byId.get(id);
    const snapshot = fallbackById.get(id);
    // Prefer saved snapshots on existing templates/sessions so editing a global
    // preset later does not silently rewrite prior conversation prompts.
    if (snapshot) {
      const color = snapshot.color || live?.color;
      resolved.push({
        id: snapshot.id,
        name: snapshot.name,
        group: snapshot.group ?? live?.group ?? "",
        ...(color ? { color } : {}),
        content: snapshot.content,
        isDeleted: libraryLoaded ? !live : false,
      });
      continue;
    }
    if (live) {
      resolved.push({
        id: live.id,
        name: live.name,
        group: live.group,
        ...(live.color ? { color: live.color } : {}),
        content: live.content,
        isDeleted: false,
      });
    }
  }
  return resolved;
}

export function composeScenarioWithPresets(
  baseScenario: string,
  presets: ReadonlyArray<Pick<AppliedUserPromptPreset, "content">>,
): string {
  const base = String(baseScenario ?? "").replace(/\r\n/g, "\n");
  const blocks = presets
    .map((preset) =>
      String(preset.content ?? "")
        .replace(/\r\n/g, "\n")
        .trim(),
    )
    .filter(Boolean);
  if (!blocks.length) {
    return base;
  }
  const trimmedBase = base.trimEnd();
  if (!trimmedBase.trim()) {
    return blocks.join("\n\n");
  }
  return [trimmedBase, ...blocks].join("\n\n");
}

export function toAppliedPresets(
  presets: ReadonlyArray<Pick<AppliedUserPromptPreset, "id" | "name" | "group" | "color" | "content">>,
): AppliedUserPromptPreset[] {
  return presets.map((preset) => ({
    id: preset.id,
    name: preset.name,
    ...(preset.group ? { group: preset.group } : {}),
    ...(preset.color ? { color: preset.color } : {}),
    content: preset.content,
  }));
}

export function reorderPresetIds(ids: readonly string[], fromIndex: number, toIndex: number): string[] {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= ids.length || toIndex >= ids.length) {
    return [...ids];
  }
  const next = [...ids];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}

export function reorderPresetIdsById(ids: readonly string[], sourceId: string, targetId: string): string[] {
  const fromIndex = ids.indexOf(sourceId);
  const toIndex = ids.indexOf(targetId);
  return reorderPresetIds(ids, fromIndex, toIndex);
}
