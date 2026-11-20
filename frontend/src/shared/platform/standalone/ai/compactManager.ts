import type { ApiConfig } from "../../slices/configTypes";
import type {
  CompactCheckpoint,
  StandaloneRawMessage,
  StandaloneSessionStore,
} from "../storage/sessionStore";
import type { StandaloneLlmAdapter } from "./adapters/types";
import type { StandaloneHttpClient } from "./httpClient";

const CJK_CHAR_RE = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]/g;

/**
 * Zero-WASM character-weighted token estimator aligned with `ai/llm/compact_manager.py`.
 * CJK ideographs average ~0.65 tokens/char; ASCII/whitespace averages ~0.30 tokens/char.
 */
export function estimateTextTokens(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  const cjkMatches = trimmed.match(CJK_CHAR_RE);
  const cjkCount = cjkMatches ? cjkMatches.length : 0;
  const otherCount = Math.max(0, trimmed.length - cjkCount);
  return Math.max(1, Math.ceil(cjkCount * 0.65 + otherCount * 0.3));
}

export function estimateMessagesTokens(messages: StandaloneRawMessage[]): number {
  let total = 0;
  for (const msg of messages) {
    total += 4 + estimateTextTokens(msg.role) + estimateTextTokens(msg.content);
  }
  return total;
}

export function getCompactionLimits(apiConfig: Partial<ApiConfig>): {
  maxContextTokens: number;
  triggerTokens: number;
  targetSummaryTokens: number;
  recentMessagesCount: number;
} {
  const maxContextTokens = Math.max(2048, Number(apiConfig.max_context_tokens) || 32000);
  const threshold = Math.min(0.95, Math.max(0.1, Number(apiConfig.compact_threshold) || 0.4));
  const targetRatio = Math.min(0.6, Math.max(0.05, Number(apiConfig.compact_target_ratio) || 0.3));
  const recentMessagesCount = Math.max(4, Number(apiConfig.history_recent_messages) || 20);
  return {
    maxContextTokens,
    triggerTokens: Math.floor(maxContextTokens * threshold),
    targetSummaryTokens: Math.max(400, Math.floor(maxContextTokens * targetRatio * 0.5)),
    recentMessagesCount,
  };
}

export function needsCompaction(estimatedTokens: number, apiConfig: Partial<ApiConfig>): boolean {
  const { triggerTokens } = getCompactionLimits(apiConfig);
  return estimatedTokens >= triggerTokens;
}

/**
 * Binary searches for the longest summary prefix that stays within `maxSummaryTokens`.
 */
export function binarySearchCapSummary(summary: string, maxSummaryTokens: number): string {
  const trimmed = summary.trim();
  if (!trimmed || maxSummaryTokens <= 0) return "";
  if (estimateTextTokens(trimmed) <= maxSummaryTokens) {
    return trimmed;
  }

  let lo = 0;
  let hi = trimmed.length;
  let best = "";
  const suffix = "\n...(较早细节已浓缩)";
  const suffixTokens = estimateTextTokens(suffix);
  const effectiveBudget = Math.max(32, maxSummaryTokens - suffixTokens);

  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const candidate = trimmed.slice(0, mid).trimEnd();
    if (estimateTextTokens(candidate) <= effectiveBudget) {
      best = candidate;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best ? `${best}${suffix}` : trimmed.slice(0, 64);
}

/**
 * Deterministic non-destructive fallback when LLM compaction fails:
 * keeps leading system messages + most recent conversation messages fitting `maxTokens`.
 */
export function trimMessagesToBudget(
  messages: StandaloneRawMessage[],
  maxTokens: number,
): StandaloneRawMessage[] {
  if (!messages.length) return [];
  const budget = Math.max(512, maxTokens);

  const leadingSystem: StandaloneRawMessage[] = [];
  let nonSystemStart = 0;
  while (nonSystemStart < messages.length && messages[nonSystemStart].role === "system") {
    leadingSystem.push(messages[nonSystemStart]);
    nonSystemStart += 1;
  }

  const tailCandidates = messages.slice(nonSystemStart);
  let usedTokens = estimateMessagesTokens(leadingSystem);

  if (usedTokens >= budget && leadingSystem.length > 0) {
    return [...leadingSystem.slice(0, 1), ...(tailCandidates.length ? [tailCandidates[tailCandidates.length - 1]] : [])];
  }

  const keptTail: StandaloneRawMessage[] = [];
  for (let i = tailCandidates.length - 1; i >= 0; i -= 1) {
    const msg = tailCandidates[i];
    const msgTokens = 4 + estimateTextTokens(msg.role) + estimateTextTokens(msg.content);
    if (keptTail.length > 0 && usedTokens + msgTokens > budget) {
      break;
    }
    keptTail.unshift(msg);
    usedTokens += msgTokens;
  }

  return [...leadingSystem, ...keptTail];
}

export interface AutoCompactInput {
  sessionId: string;
  branchId?: string;
  systemPrompt: string;
  sessionStore: StandaloneSessionStore;
  apiConfig: ApiConfig;
  llmAdapter: StandaloneLlmAdapter;
  httpClient: StandaloneHttpClient;
  apiKey: string;
  baseUrl: string;
  model: string;
  lastUsageTokens?: number;
  signal?: AbortSignal;
}

export interface AutoCompactResult {
  compacted: boolean;
  checkpoint: CompactCheckpoint | null;
  error?: string;
}

export async function autoCompactIfNeeded(input: AutoCompactInput): Promise<AutoCompactResult> {
  const {
    sessionId,
    branchId,
    systemPrompt,
    sessionStore,
    apiConfig,
    llmAdapter,
    httpClient,
    apiKey,
    baseUrl,
    model,
    lastUsageTokens,
    signal,
  } = input;

  const view = sessionStore.buildActiveLlmMessages(sessionId, systemPrompt, { branchId });
  const currentTokens = Math.max(lastUsageTokens ?? 0, estimateMessagesTokens(view.messages));
  if (!needsCompaction(currentTokens, apiConfig)) {
    return { compacted: false, checkpoint: view.checkpoint };
  }

  const allTurns = sessionStore.listTurns(sessionId, branchId);
  const nonOptionTurns = allTurns.filter((node) => node.role !== "options");
  const { recentMessagesCount, targetSummaryTokens } = getCompactionLimits(apiConfig);

  if (nonOptionTurns.length <= recentMessagesCount) {
    return { compacted: false, checkpoint: view.checkpoint };
  }

  const anchorCutoffIndex = nonOptionTurns.length - recentMessagesCount;
  const minSeqExclusive = view.checkpoint?.upToSeq ?? 0;
  const turnsToSummarize = nonOptionTurns
    .slice(0, anchorCutoffIndex)
    .filter((node) => node.seq > minSeqExclusive);

  if (!turnsToSummarize.length) {
    return { compacted: false, checkpoint: view.checkpoint };
  }

  const upToSeq = turnsToSummarize[turnsToSummarize.length - 1].seq;
  const transcriptLines = turnsToSummarize.map((node) => {
    const label = node.speaker ? node.speaker : node.role === "user" ? "玩家" : "旁白";
    return `${label}: ${node.plainText || node.rawMessage.content}`;
  });

  const userPromptParts: string[] = [];
  if (view.checkpoint?.rollingSummary) {
    userPromptParts.push(`【已有剧情前情摘要】\n${view.checkpoint.rollingSummary}`);
  }
  userPromptParts.push(`【需要合并压缩的新增剧情对话】\n${transcriptLines.join("\n")}`);
  userPromptParts.push(
    "请将以上信息整合为一份简练、客观的中文滚动摘要，保留重要人物关系变化、关键约定、情绪转折与当前场景状态，避免流水账。",
  );

  try {
    const result = await llmAdapter.complete(
      {
        provider: apiConfig.llm_provider,
        apiKey,
        baseUrl,
        model,
        messages: [
          {
            role: "system",
            content: "你是剧情记忆归档助手，负责输出紧凑准确的对话总结。",
          },
          {
            role: "user",
            content: userPromptParts.join("\n\n"),
          },
        ],
        temperature: 0.2,
        maxTokens: Math.min(2048, targetSummaryTokens + 256),
        signal,
      },
      httpClient,
    );

    const cappedSummary = binarySearchCapSummary(result.content, targetSummaryTokens);
    if (!cappedSummary) {
      return { compacted: false, checkpoint: view.checkpoint };
    }

    const saved = await sessionStore.saveCompactCheckpoint(
      sessionId,
      {
        upToSeq,
        rollingSummary: cappedSummary,
        tokenEstimate: estimateTextTokens(cappedSummary),
      },
      branchId,
    );
    return { compacted: true, checkpoint: saved };
  } catch (error) {
    // Non-destructive failure rule: never overwrite checkpoints or delete TurnNodes on network failure
    return {
      compacted: false,
      checkpoint: view.checkpoint,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
