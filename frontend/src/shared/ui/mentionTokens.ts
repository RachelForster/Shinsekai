export interface MentionOption {
  color?: string;
  id: string;
  label: string;
}

export interface MentionQuery {
  query: string;
  start: number;
}

export interface MentionSegment {
  option?: MentionOption;
  type: "mention" | "text";
  value: string;
}

export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function characterMentionOptions(
  characters: Array<{ color?: string; name: string }>,
  userLabel: string,
): MentionOption[] {
  const seen = new Set<string>();
  const options: MentionOption[] = [{ color: "#6b7280", id: "user", label: userLabel }];
  seen.add(userLabel);
  for (const character of characters) {
    const label = character.name.trim();
    if (!label || seen.has(label)) {
      continue;
    }
    seen.add(label);
    options.push({ color: character.color, id: character.name, label });
  }
  return options;
}

export function mentionQueryAt(value: string, caret: number): MentionQuery | null {
  const safeCaret = Math.max(0, Math.min(caret, value.length));
  const before = value.slice(0, safeCaret);
  const at = before.lastIndexOf("@");
  if (at < 0) {
    return null;
  }
  if (at > 0 && !/\s/.test(before[at - 1] ?? "")) {
    return null;
  }
  const query = before.slice(at + 1);
  if (/[\s\n]/.test(query)) {
    return null;
  }
  return { query, start: at };
}

export function resolveMentionCaret(value: string, caret: number) {
  if (mentionQueryAt(value, caret)) {
    return caret;
  }
  if (caret === 0 && mentionQueryAt(value, value.length)) {
    return value.length;
  }
  return caret;
}

export const MENTION_RECENT_STORAGE_KEY = "shinsekai-mention-recent";

function getLocalStorage() {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function parseRecentMentionIds(raw: string | null): string[] {
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    const ids: string[] = [];
    const seen = new Set<string>();
    for (const item of parsed) {
      if (typeof item !== "string" || !item || seen.has(item)) {
        continue;
      }
      seen.add(item);
      ids.push(item);
    }
    return ids;
  } catch {
    return [];
  }
}

export function readRecentMentionIds(): string[] {
  try {
    return parseRecentMentionIds(getLocalStorage()?.getItem(MENTION_RECENT_STORAGE_KEY) ?? null);
  } catch {
    return [];
  }
}

export function rememberRecentMentionId(recentIds: string[], id: string, limit = 32): string[] {
  if (!id) {
    return recentIds;
  }
  return [id, ...recentIds.filter((item) => item !== id)].slice(0, limit);
}

export function writeRecentMentionIds(recentIds: string[]) {
  try {
    getLocalStorage()?.setItem(MENTION_RECENT_STORAGE_KEY, JSON.stringify(recentIds));
  } catch {
    // localStorage may be unavailable in restricted browser contexts.
  }
}

export function sortMentionOptions(options: MentionOption[], recentIds: string[]): MentionOption[] {
  const rank = new Map(recentIds.map((id, index) => [id, index]));
  return options
    .map((option, index) => ({ index, option, rank: rank.get(option.id) }))
    .sort((left, right) => {
      if (left.rank == null && right.rank == null) {
        return left.index - right.index;
      }
      if (left.rank == null) {
        return 1;
      }
      if (right.rank == null) {
        return -1;
      }
      return left.rank - right.rank;
    })
    .map((item) => item.option);
}

export function scrollChildIntoContainer(
  container: Pick<HTMLElement, "clientHeight" | "scrollTop">,
  child: Pick<HTMLElement, "offsetHeight" | "offsetTop">,
) {
  const top = child.offsetTop;
  const bottom = top + child.offsetHeight;
  const viewBottom = container.scrollTop + container.clientHeight;
  if (bottom > viewBottom) {
    container.scrollTop = bottom - container.clientHeight;
    return;
  }
  if (top < container.scrollTop) {
    container.scrollTop = top;
  }
}

export function filterMentionOptions(options: MentionOption[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return options;
  }
  return options.filter(
    (option) => option.label.toLowerCase().includes(needle) || option.id.toLowerCase().includes(needle),
  );
}

export function insertMention(value: string, caret: number, option: MentionOption, start: number) {
  const token = `@${option.label} `;
  const resolved = resolveMentionCaret(value, caret);
  const query = mentionQueryAt(value, resolved);
  const from = query?.start ?? Math.max(0, Math.min(start, value.length));
  const to = Math.max(from, resolved);
  return {
    caret: from + token.length,
    value: `${value.slice(0, from)}${token}${value.slice(to)}`,
  };
}

export function splitMentionSegments(value: string, options: MentionOption[]): MentionSegment[] {
  const labels = [...options]
    .map((option) => option.label.trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);
  if (!value) {
    return [{ type: "text", value: "" }];
  }
  if (!labels.length) {
    return [{ type: "text", value }];
  }
  const byLabel = new Map(options.map((option) => [option.label, option]));
  const pattern = new RegExp(`@(${labels.map(escapeRegExp).join("|")})(?=$|\\s|[.,!?;:：，。！？])`, "g");
  const segments: MentionSegment[] = [];
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({ type: "text", value: value.slice(cursor, index) });
    }
    const label = match[1] ?? "";
    const option = byLabel.get(label);
    segments.push({
      option,
      type: "mention",
      value: match[0],
    });
    cursor = index + match[0].length;
  }
  if (cursor < value.length) {
    segments.push({ type: "text", value: value.slice(cursor) });
  }
  return segments.length ? segments : [{ type: "text", value }];
}
