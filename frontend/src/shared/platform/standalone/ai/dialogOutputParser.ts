import type { ChatStat, ChatStatIcon } from "../../slices/chatTypes";

export interface ParsedDialogSpeechItem {
  kind: "speech";
  characterName: string;
  speech: string;
  translate?: string;
  sprite?: number | string;
  vibe?: string;
  outfit?: string;
  leave?: boolean;
  isNarration: boolean;
}

export interface ParsedDialogPortraitItem {
  kind: "portrait";
  characterName: string;
  sprite?: number | string;
  vibe?: string;
  outfit?: string;
  leave?: boolean;
}

export interface ParsedDialogSceneItem {
  kind: "scene";
  sprite?: number | string;
  vibe?: string;
}

export interface ParsedDialogBgmItem {
  kind: "bgm";
  sprite?: number | string;
  vibe?: string;
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
  | ParsedDialogPortraitItem
  | ParsedDialogSceneItem
  | ParsedDialogBgmItem
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

function parseStatSpeechLines(speech: string): ChatStat[] {
  const results: ChatStat[] = [];
  for (const rawLine of speech.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || !line.includes("|")) continue;
    const parts = line.split("|").map((part) => part.trim());
    if (parts.length < 3) continue;
    const [iconRaw, label, valueRaw, maxRaw] = parts;
    const value = Number(valueRaw);
    if (!label || !Number.isFinite(value)) continue;
    const max = maxRaw !== undefined && maxRaw !== "" ? Number(maxRaw) : undefined;
    results.push({
      icon: normalizeStatIcon(iconRaw),
      label,
      value,
      ...(max !== undefined && Number.isFinite(max) ? { max } : {}),
    });
  }
  return results;
}

function mapRawDialogEntry(rawItem: unknown, fallbackCharacterName: string): ParsedDialogEntry | null {
  if (!rawItem || typeof rawItem !== "object") return null;
  const item = rawItem as Record<string, unknown>;

  const rawName = String(item.character_name ?? item.speaker ?? item.name ?? "").trim();
  const upperName = rawName.toUpperCase();

  // Internal COT & unsupported CG generation tokens should never be spoken as dialog
  if (upperName === "COT" || upperName === "思维链" || upperName === "CG") {
    return null;
  }

  const speech = String(item.speech ?? item.text ?? item.content ?? "").trim();
  const sprite = typeof item.sprite === "number" || typeof item.sprite === "string" ? item.sprite : undefined;
  const vibe = typeof item.vibe === "string" && item.vibe.trim() ? item.vibe.trim() : undefined;

  if (upperName === "CHOICE" || upperName === "OPTIONS" || upperName === "选项") {
    const rawArray = Array.isArray(item.options) ? item.options : Array.isArray(item.choices) ? item.choices : null;
    const options = rawArray
      ? rawArray.map((opt) => String(opt ?? "").trim()).filter(Boolean)
      : speech
          .split("/")
          .map((opt) => opt.trim())
          .filter(Boolean);
    if (!options.length) return null;
    return { kind: "choice", options };
  }

  if (upperName === "STAT" || upperName === "STATS" || upperName === "数值") {
    const arrayStats = normalizeStatList(item.stats ?? item.items);
    const stats = arrayStats.length ? arrayStats : parseStatSpeechLines(speech);
    if (!stats.length) return null;
    return { kind: "stat", stats };
  }

  if (upperName === "SCENE" || upperName === "场景") {
    if (sprite === undefined && !vibe) return null;
    return { kind: "scene", sprite, vibe };
  }

  if (upperName === "BGM") {
    if (sprite === undefined && !vibe) return null;
    return { kind: "bgm", sprite, vibe };
  }

  const isNarration = upperName === "NARR" || upperName === "NARRATION" || upperName === "旁白";
  const characterName = isNarration ? "NARR" : rawName || fallbackCharacterName;
  const translate = typeof item.translate === "string" && item.translate.trim() ? item.translate.trim() : undefined;
  const outfit = typeof item.outfit === "string" && item.outfit.trim() ? item.outfit.trim() : undefined;
  const effectRaw = typeof item.effect === "string" ? item.effect.trim() : "";
  const leave = /^leave$/i.test(effectRaw);

  if (!speech) {
    if (!isNarration && rawName && (sprite !== undefined || vibe !== undefined || leave)) {
      return {
        kind: "portrait",
        characterName,
        sprite,
        vibe,
        outfit,
        ...(leave ? { leave: true } : {}),
      };
    }
    return null;
  }

  return {
    kind: "speech",
    characterName,
    speech,
    translate,
    sprite,
    vibe,
    outfit,
    ...(leave ? { leave: true } : {}),
    isNarration,
  };
}

export function parseStandaloneDialogOutput(rawText: string, fallbackCharacterName: string): ParsedDialogEntry[] {
  const cleaned = stripThinkBlocks(rawText);
  if (!cleaned) return [];

  const candidateJson = extractCandidateJson(cleaned);
  if (candidateJson) {
    try {
      const parsed = tryParseRelaxedJson(candidateJson);
      const list = Array.isArray(parsed)
        ? parsed
        : parsed && typeof parsed === "object" && Array.isArray((parsed as { dialog?: unknown[] }).dialog)
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
