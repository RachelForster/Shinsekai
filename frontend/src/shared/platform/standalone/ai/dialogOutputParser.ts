import type { ChatStat, ChatStatIcon } from "../../slices/chatTypes";

export interface ParsedDialogSpeechItem {
  kind: "speech";
  characterName: string;
  speech: string;
  translate?: string;
  sprite?: number | string;
  outfit?: string;
  isNarration: boolean;
}

export interface ParsedDialogChoiceItem {
  kind: "choice";
  options: string[];
}

export interface ParsedDialogStatItem {
  kind: "stat";
  stats: ChatStat[];
}

export type ParsedDialogEntry =
  | ParsedDialogSpeechItem
  | ParsedDialogChoiceItem
  | ParsedDialogStatItem;

const VALID_STAT_ICONS = new Set<ChatStatIcon>([
  "clock",
  "coins",
  "gauge",
  "heart",
  "shield",
  "sparkles",
  "star",
  "target",
  "zap",
]);

function stripThinkBlocks(raw: string): string {
  return raw.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
}

function extractCandidateJson(text: string): string | null {
  const fenceMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenceMatch ? fenceMatch[1].trim() : text.trim();

  const firstBrace = candidate.indexOf("{");
  const lastBrace = candidate.lastIndexOf("}");
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    return candidate.slice(firstBrace, lastBrace + 1);
  }

  const firstBracket = candidate.indexOf("[");
  const lastBracket = candidate.lastIndexOf("]");
  if (firstBracket >= 0 && lastBracket > firstBracket) {
    return candidate.slice(firstBracket, lastBracket + 1);
  }
  return null;
}

function tryParseRelaxedJson(rawJson: string): unknown {
  try {
    return JSON.parse(rawJson);
  } catch {
    // Strip trailing commas before } or ] emitted by smaller open-source models
    const repaired = rawJson.replace(/,\s*([}\]])/g, "$1");
    return JSON.parse(repaired);
  }
}

function normalizeStatIcon(icon: unknown): ChatStatIcon {
  const str = typeof icon === "string" ? icon.trim().toLowerCase() : "";
  return VALID_STAT_ICONS.has(str as ChatStatIcon) ? (str as ChatStatIcon) : "heart";
}

function normalizeStatList(rawStats: unknown): ChatStat[] {
  if (!Array.isArray(rawStats)) return [];
  const results: ChatStat[] = [];
  for (const row of rawStats) {
    if (!row || typeof row !== "object") continue;
    const item = row as Record<string, unknown>;
    const label = String(item.label ?? item.name ?? "").trim();
    const value = Number(item.value ?? item.score ?? 0);
    if (!label || !Number.isFinite(value)) continue;
    const max = item.max !== undefined ? Number(item.max) : undefined;
    results.push({
      icon: normalizeStatIcon(item.icon),
      label,
      value,
      ...(max !== undefined && Number.isFinite(max) ? { max } : {}),
    });
  }
  return results;
}

function mapRawDialogEntry(
  rawItem: unknown,
  fallbackCharacterName: string,
): ParsedDialogEntry | null {
  if (!rawItem || typeof rawItem !== "object") return null;
  const item = rawItem as Record<string, unknown>;

  const rawName = String(item.character_name ?? item.speaker ?? item.name ?? "").trim();
  const upperName = rawName.toUpperCase();

  if (upperName === "CHOICE" || upperName === "OPTIONS") {
    const rawOptions = Array.isArray(item.options)
      ? item.options
      : Array.isArray(item.choices)
        ? item.choices
        : [];
    const options = rawOptions.map((opt) => String(opt ?? "").trim()).filter(Boolean);
    if (!options.length) return null;
    return { kind: "choice", options };
  }

  if (upperName === "STAT" || upperName === "STATS") {
    const stats = normalizeStatList(item.stats ?? item.items);
    if (!stats.length) return null;
    return { kind: "stat", stats };
  }

  const speech = String(item.speech ?? item.text ?? item.content ?? "").trim();
  if (!speech) return null;

  const isNarration = upperName === "NARR" || upperName === "NARRATION" || upperName === "旁白";
  const characterName = isNarration ? "NARR" : rawName || fallbackCharacterName;
  const translate = typeof item.translate === "string" && item.translate.trim() ? item.translate.trim() : undefined;
  const sprite =
    typeof item.sprite === "number" || typeof item.sprite === "string" ? item.sprite : undefined;
  const outfit = typeof item.outfit === "string" && item.outfit.trim() ? item.outfit.trim() : undefined;

  return {
    kind: "speech",
    characterName,
    speech,
    translate,
    sprite,
    outfit,
    isNarration,
  };
}

export function parseStandaloneDialogOutput(
  rawText: string,
  fallbackCharacterName: string,
): ParsedDialogEntry[] {
  const cleaned = stripThinkBlocks(rawText);
  if (!cleaned) return [];

  const candidateJson = extractCandidateJson(cleaned);
  if (candidateJson) {
    try {
      const parsed = tryParseRelaxedJson(candidateJson);
      const list = Array.isArray(parsed)
        ? parsed
        : parsed &&
            typeof parsed === "object" &&
            Array.isArray((parsed as { dialog?: unknown[] }).dialog)
          ? (parsed as { dialog: unknown[] }).dialog
          : [];
      const mapped = list
        .map((entry) => mapRawDialogEntry(entry, fallbackCharacterName))
        .filter((entry): entry is ParsedDialogEntry => entry !== null);
      if (mapped.length) {
        return mapped;
      }
    } catch {
      // Fall back smoothly to plain-text splitting below
    }
  }

  // Fallback for non-JSON plain text responses
  const plainLines = cleaned
    .replace(/^```[\s\S]*?```$/gm, "")
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .slice(0, 4);

  if (!plainLines.length) {
    return [
      {
        kind: "speech",
        characterName: fallbackCharacterName,
        speech: cleaned,
        isNarration: false,
      },
    ];
  }

  return plainLines.map((line) => ({
    kind: "speech",
    characterName: fallbackCharacterName,
    speech: line,
    isNarration: false,
  }));
}
