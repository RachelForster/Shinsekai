import type {
  CharacterOutfitState,
  ChatHistoryRole,
  ChatLaunchPayload,
  ChatSprite,
  ChatStat,
  ConversationSummary,
} from "../../slices/chatTypes";
import {
  idbDelete,
  idbDeleteMany,
  idbGetAll,
  idbPut,
  idbPutMany,
} from "./indexedDbStore";

export interface StandaloneRawMessage {
  role: "system" | "user" | "assistant";
  content: string;
  name?: string;
}

export type StandaloneOutfitSnapshot = Record<string, CharacterOutfitState>;

export interface StandaloneStageSnapshot {
  backgroundPath: string;
  bgmPath: string;
  cgPath: string;
  sprites: ChatSprite[];
  stats: ChatStat[];
}

export interface TurnNode {
  nodeKey: string;
  sessionId: string;
  branchId: string;
  seq: number;
  turnId: string;
  role: ChatHistoryRole;
  speaker: string;
  rawMessage: StandaloneRawMessage;
  renderedHtml: string;
  plainText: string;
  options?: string[];
  selectedIndex?: number | null;
  voiceId?: string;
  voiceUrl?: string;
  outfitSnapshot?: StandaloneOutfitSnapshot;
  stageSnapshot?: StandaloneStageSnapshot | null;
  revertUserIndex?: number;
  createdAtMs: number;
}

export interface CompactCheckpoint {
  checkpointKey: string;
  checkpointId: string;
  sessionId: string;
  branchId: string;
  upToSeq: number;
  rollingSummary: string;
  tokenEstimate?: number;
  createdAtMs: number;
}

export interface StandaloneBranchInfo {
  branchId: string;
  label: string;
  parentBranchId?: string;
  forkedAtSeq?: number;
  createdAtMs: number;
}

export interface StandaloneSessionRecord {
  sessionId: string;
  historyPath: string;
  title: string;
  characters: string[];
  primaryCharacters: string[];
  activeBranchId: string;
  branches: Record<string, StandaloneBranchInfo>;
  payload: ChatLaunchPayload;
  autoOutfitSwitch: boolean;
  outfits: StandaloneOutfitSnapshot;
  stats: ChatStat[];
  prologueCompleted?: boolean;
  prologueStepId?: string;
  preview: string;
  updatedAtMs: number;
  createdAtMs: number;
}

export interface AppendTurnInput {
  turnId?: string;
  role: ChatHistoryRole;
  speaker?: string;
  rawContent?: string;
  renderedHtml?: string;
  plainText: string;
  options?: string[];
  selectedIndex?: number | null;
  voiceId?: string;
  voiceUrl?: string;
  outfitSnapshot?: StandaloneOutfitSnapshot;
  stageSnapshot?: StandaloneStageSnapshot | null;
  createdAtMs?: number;
}

export interface TruncateResult {
  removedTurnCount: number;
  removedCheckpointCount: number;
  survivingLastTurn: TurnNode | null;
  activeCheckpoint: CompactCheckpoint | null;
  restoredOutfits?: StandaloneOutfitSnapshot;
  restoredStage?: StandaloneStageSnapshot | null;
}

export interface ActiveLlmContextView {
  checkpoint: CompactCheckpoint | null;
  messages: StandaloneRawMessage[];
  tailNodes: TurnNode[];
}

function makeNodeKey(sessionId: string, branchId: string, seq: number): string {
  return `${sessionId}::${branchId}::${String(seq).padStart(8, "0")}`;
}

function makeCheckpointKey(sessionId: string, branchId: string, upToSeq: number): string {
  return `${sessionId}::${branchId}::${String(upToSeq).padStart(8, "0")}`;
}

function cloneDeep<T>(value: T): T {
  return structuredClone(value);
}

/**
 * 1:1 TypeScript port of Shinsekai's non-destructive single-timeline session store
 * (`core/chat_history/in_memory.py` + `models.py`):
 * - `TurnNode`s are never deleted or overwritten during context compaction.
 * - `CompactCheckpoint`s anchor rolling summaries at `upToSeq`.
 * - `buildFullRawMessages` returns 100% of raw history for UI/replay.
 * - `buildActiveLlmMessages` projects `[System] + [Rolling Summary] + [Tail > upToSeq]`.
 * - `truncateAfter` cascades deletion to both future `TurnNode`s and `CompactCheckpoint`s with `upToSeq > cutoffSeq`.
 */
export class StandaloneSessionStore {
  private sessions = new Map<string, StandaloneSessionRecord>();
  private turnsBySessionBranch = new Map<string, TurnNode[]>();
  private checkpointsBySessionBranch = new Map<string, CompactCheckpoint[]>();
  private hydrated = false;
  private hydratePromise: Promise<void> | null = null;

  private branchMapKey(sessionId: string, branchId: string): string {
    return `${sessionId}::${branchId}`;
  }

  async hydrate(): Promise<void> {
    if (this.hydrated) return;
    if (this.hydratePromise) return this.hydratePromise;

    this.hydratePromise = (async () => {
      const [sessionRows, turnRows, checkpointRows] = await Promise.all([
        idbGetAll<StandaloneSessionRecord>("sessions"),
        idbGetAll<TurnNode>("turn_nodes"),
        idbGetAll<CompactCheckpoint>("compact_checkpoints"),
      ]);

      for (const session of sessionRows) {
        if (session?.sessionId && !this.sessions.has(session.sessionId)) {
          this.sessions.set(session.sessionId, session);
        }
      }

      const groupedTurns = new Map<string, TurnNode[]>();
      for (const node of turnRows) {
        if (!node?.sessionId || !node.branchId) continue;
        const key = this.branchMapKey(node.sessionId, node.branchId);
        const list = groupedTurns.get(key) ?? [];
        list.push(node);
        groupedTurns.set(key, list);
      }
      for (const [key, list] of groupedTurns.entries()) {
        if (!this.turnsBySessionBranch.has(key)) {
          list.sort((a, b) => a.seq - b.seq);
          this.turnsBySessionBranch.set(key, list);
        }
      }

      const groupedCheckpoints = new Map<string, CompactCheckpoint[]>();
      for (const cp of checkpointRows) {
        if (!cp?.sessionId || !cp.branchId) continue;
        const key = this.branchMapKey(cp.sessionId, cp.branchId);
        const list = groupedCheckpoints.get(key) ?? [];
        list.push(cp);
        groupedCheckpoints.set(key, list);
      }
      for (const [key, list] of groupedCheckpoints.entries()) {
        if (!this.checkpointsBySessionBranch.has(key)) {
          list.sort((a, b) => a.upToSeq - b.upToSeq);
          this.checkpointsBySessionBranch.set(key, list);
        }
      }

      this.hydrated = true;
    })();

    return this.hydratePromise;
  }

  listSessions(): StandaloneSessionRecord[] {
    return Array.from(this.sessions.values())
      .map((s) => cloneDeep(s))
      .sort((a, b) => b.updatedAtMs - a.updatedAtMs);
  }

  listConversationSummaries(): ConversationSummary[] {
    return this.listSessions().map((session) => ({
      id: session.sessionId,
      sessionId: session.sessionId,
      title: session.title,
      characters: [...session.characters],
      preview: session.preview,
      updatedAt: Math.floor(session.updatedAtMs / 1000),
      kind: session.payload.storyPath ? "story" : "normal",
      storyPath: session.payload.storyPath ?? "",
      historyPath: session.historyPath,
      hasSettings: true,
      memoryMode: session.payload.memoryMode ?? "isolated",
      autoOutfitSwitch: session.autoOutfitSwitch,
      outfits: cloneDeep(session.outfits),
    }));
  }

  getSession(sessionId: string): StandaloneSessionRecord | undefined {
    const found = this.sessions.get(sessionId);
    return found ? cloneDeep(found) : undefined;
  }

  getSessionByHistoryPath(historyPath: string): StandaloneSessionRecord | undefined {
    const normalized = historyPath.trim();
    for (const session of this.sessions.values()) {
      if (session.historyPath === normalized || session.sessionId === normalized) {
        return cloneDeep(session);
      }
    }
    return undefined;
  }

  async ensureSession(input: {
    sessionId?: string;
    historyPath: string;
    title: string;
    payload: ChatLaunchPayload;
    outfits?: StandaloneOutfitSnapshot;
    stats?: ChatStat[];
  }): Promise<StandaloneSessionRecord> {
    const existing =
      (input.sessionId ? this.sessions.get(input.sessionId) : undefined) ??
      this.getSessionByHistoryPath(input.historyPath);

    const now = Date.now();
    if (existing) {
      const updated: StandaloneSessionRecord = {
        ...existing,
        title: input.title || existing.title,
        characters: input.payload.characters.length ? [...input.payload.characters] : existing.characters,
        primaryCharacters: input.payload.primaryCharacters?.length
          ? [...input.payload.primaryCharacters]
          : existing.primaryCharacters,
        payload: cloneDeep(input.payload),
        autoOutfitSwitch: input.payload.autoOutfitSwitch ?? existing.autoOutfitSwitch,
        outfits: input.outfits ? cloneDeep(input.outfits) : existing.outfits,
        stats: input.stats ? cloneDeep(input.stats) : existing.stats,
        updatedAtMs: now,
      };
      this.sessions.set(updated.sessionId, updated);
      await idbPut("sessions", updated);
      return cloneDeep(updated);
    }

    const sessionId = input.sessionId || `session-${now}-${Math.random().toString(36).slice(2, 8)}`;
    const mainBranch: StandaloneBranchInfo = {
      branchId: "main",
      label: "主线",
      createdAtMs: now,
    };
    const created: StandaloneSessionRecord = {
      sessionId,
      historyPath: input.historyPath || `./data/history/${sessionId}.json`,
      title: input.title || "新对话",
      characters: [...input.payload.characters],
      primaryCharacters: [...(input.payload.primaryCharacters ?? input.payload.characters)],
      activeBranchId: "main",
      branches: { main: mainBranch },
      payload: cloneDeep(input.payload),
      autoOutfitSwitch: Boolean(input.payload.autoOutfitSwitch),
      outfits: input.outfits ? cloneDeep(input.outfits) : {},
      stats: input.stats ? cloneDeep(input.stats) : [],
      preview: "",
      updatedAtMs: now,
      createdAtMs: now,
    };
    this.sessions.set(sessionId, created);
    await idbPut("sessions", created);
    return cloneDeep(created);
  }

  async updateSessionMeta(
    sessionId: string,
    patch: Partial<
      Pick<
        StandaloneSessionRecord,
        | "title"
        | "activeBranchId"
        | "autoOutfitSwitch"
        | "outfits"
        | "stats"
        | "prologueCompleted"
        | "prologueStepId"
        | "preview"
        | "characters"
        | "payload"
      >
    >,
  ): Promise<StandaloneSessionRecord | undefined> {
    const existing = this.sessions.get(sessionId);
    if (!existing) return undefined;
    const updated: StandaloneSessionRecord = {
      ...existing,
      ...cloneDeep(patch),
      updatedAtMs: Date.now(),
    };
    this.sessions.set(sessionId, updated);
    await idbPut("sessions", updated);
    return cloneDeep(updated);
  }

  async deleteSession(sessionId: string): Promise<void> {
    const existing = this.sessions.get(sessionId);
    if (!existing) return;
    const branchIds = Object.keys(existing.branches);
    const nodeKeys: string[] = [];
    const cpKeys: string[] = [];

    for (const branchId of branchIds) {
      const bKey = this.branchMapKey(sessionId, branchId);
      for (const node of this.turnsBySessionBranch.get(bKey) ?? []) {
        nodeKeys.push(node.nodeKey);
      }
      for (const cp of this.checkpointsBySessionBranch.get(bKey) ?? []) {
        cpKeys.push(cp.checkpointKey);
      }
      this.turnsBySessionBranch.delete(bKey);
      this.checkpointsBySessionBranch.delete(bKey);
    }

    this.sessions.delete(sessionId);
    await Promise.all([
      idbDelete("sessions", sessionId),
      idbDeleteMany("turn_nodes", nodeKeys),
      idbDeleteMany("compact_checkpoints", cpKeys),
    ]);
  }

  private resolveBranchId(sessionId: string, branchId?: string): string {
    if (branchId) return branchId;
    return this.sessions.get(sessionId)?.activeBranchId ?? "main";
  }

  listTurns(sessionId: string, branchId?: string): TurnNode[] {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const list = this.turnsBySessionBranch.get(this.branchMapKey(sessionId, targetBranch)) ?? [];
    return cloneDeep(list);
  }

  listCheckpoints(sessionId: string, branchId?: string): CompactCheckpoint[] {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const list = this.checkpointsBySessionBranch.get(this.branchMapKey(sessionId, targetBranch)) ?? [];
    return cloneDeep(list);
  }

  getLatestCheckpoint(sessionId: string, branchId?: string, maxSeq?: number): CompactCheckpoint | null {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const list = this.checkpointsBySessionBranch.get(this.branchMapKey(sessionId, targetBranch)) ?? [];
    const ceiling = maxSeq ?? Number.POSITIVE_INFINITY;
    let best: CompactCheckpoint | null = null;
    for (const cp of list) {
      if (cp.upToSeq <= ceiling && (!best || cp.upToSeq >= best.upToSeq)) {
        best = cp;
      }
    }
    return best ? cloneDeep(best) : null;
  }

  async appendTurn(sessionId: string, input: AppendTurnInput, branchId?: string): Promise<TurnNode> {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const bKey = this.branchMapKey(sessionId, targetBranch);
    const list = this.turnsBySessionBranch.get(bKey) ?? [];
    const nextSeq = list.length ? list[list.length - 1].seq + 1 : 1;
    const now = input.createdAtMs ?? Date.now();

    let userTurnCountBefore = 0;
    for (const item of list) {
      if (item.role === "user") {
        userTurnCountBefore += 1;
      }
    }

    const llmRole: StandaloneRawMessage["role"] =
      input.role === "user" ? "user" : input.role === "system" ? "system" : "assistant";

    const speakerPrefix =
      input.speaker && input.role === "assistant" ? `【${input.speaker}】` : "";
    const rawContent = input.rawContent ?? `${speakerPrefix}${input.plainText}`;

    const node: TurnNode = {
      nodeKey: makeNodeKey(sessionId, targetBranch, nextSeq),
      sessionId,
      branchId: targetBranch,
      seq: nextSeq,
      turnId: input.turnId ?? `turn-${sessionId}-${targetBranch}-${nextSeq}`,
      role: input.role,
      speaker: input.speaker ?? "",
      rawMessage: {
        role: llmRole,
        content: rawContent,
        ...(input.speaker ? { name: input.speaker } : {}),
      },
      renderedHtml: input.renderedHtml ?? input.plainText,
      plainText: input.plainText,
      options: input.options ? [...input.options] : undefined,
      selectedIndex: input.selectedIndex,
      voiceId: input.voiceId,
      voiceUrl: input.voiceUrl,
      outfitSnapshot: input.outfitSnapshot ? cloneDeep(input.outfitSnapshot) : undefined,
      stageSnapshot: input.stageSnapshot !== undefined ? cloneDeep(input.stageSnapshot) : undefined,
      revertUserIndex: input.role === "user" ? userTurnCountBefore : undefined,
      createdAtMs: now,
    };

    list.push(node);
    this.turnsBySessionBranch.set(bKey, list);
    await idbPut("turn_nodes", node);

    const session = this.sessions.get(sessionId);
    if (session) {
      session.updatedAtMs = now;
      if (input.plainText.trim()) {
        session.preview = input.plainText.trim().slice(0, 90);
      }
      if (input.outfitSnapshot) {
        session.outfits = cloneDeep(input.outfitSnapshot);
      }
      if (input.stageSnapshot?.stats) {
        session.stats = cloneDeep(input.stageSnapshot.stats);
      }
      await idbPut("sessions", session);
    }

    return cloneDeep(node);
  }

  async markOptionSelected(
    sessionId: string,
    selectedIndex: number,
    branchId?: string,
  ): Promise<TurnNode | null> {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const bKey = this.branchMapKey(sessionId, targetBranch);
    const list = this.turnsBySessionBranch.get(bKey) ?? [];
    for (let i = list.length - 1; i >= 0; i -= 1) {
      if (list[i].role === "options") {
        list[i] = { ...list[i], selectedIndex };
        await idbPut("turn_nodes", list[i]);
        return cloneDeep(list[i]);
      }
    }
    return null;
  }

  async saveCompactCheckpoint(
    sessionId: string,
    input: {
      upToSeq: number;
      rollingSummary: string;
      tokenEstimate?: number;
    },
    branchId?: string,
  ): Promise<CompactCheckpoint> {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const bKey = this.branchMapKey(sessionId, targetBranch);
    const list = this.checkpointsBySessionBranch.get(bKey) ?? [];
    const now = Date.now();
    const checkpointKey = makeCheckpointKey(sessionId, targetBranch, input.upToSeq);

    const cp: CompactCheckpoint = {
      checkpointKey,
      checkpointId: `cp-${sessionId}-${targetBranch}-${input.upToSeq}-${now}`,
      sessionId,
      branchId: targetBranch,
      upToSeq: input.upToSeq,
      rollingSummary: input.rollingSummary.trim(),
      tokenEstimate: input.tokenEstimate,
      createdAtMs: now,
    };

    const existingIdx = list.findIndex((item) => item.upToSeq === input.upToSeq);
    if (existingIdx >= 0) {
      list[existingIdx] = cp;
    } else {
      list.push(cp);
      list.sort((a, b) => a.upToSeq - b.upToSeq);
    }
    this.checkpointsBySessionBranch.set(bKey, list);
    await idbPut("compact_checkpoints", cp);
    return cloneDeep(cp);
  }

  /**
   * Returns 100% of raw messages across the entire branch timeline.
   * Never drops or mutates entries even when multiple CompactCheckpoints exist.
   */
  buildFullRawMessages(sessionId: string, branchId?: string): StandaloneRawMessage[] {
    const turns = this.listTurns(sessionId, branchId);
    return turns
      .filter((node) => node.role !== "options")
      .map((node) => cloneDeep(node.rawMessage));
  }

  /**
   * Builds the active LLM prompt context view:
   * `[systemPrompt] + [latest CompactCheckpoint <= maxSeq] + [TurnNodes with seq > checkpoint.upToSeq]`.
   */
  buildActiveLlmMessages(
    sessionId: string,
    systemPrompt: string,
    options?: { branchId?: string; maxSeq?: number },
  ): ActiveLlmContextView {
    const targetBranch = this.resolveBranchId(sessionId, options?.branchId);
    const ceiling = options?.maxSeq ?? Number.POSITIVE_INFINITY;
    const checkpoint = this.getLatestCheckpoint(sessionId, targetBranch, ceiling);
    const lowerExclusive = checkpoint ? checkpoint.upToSeq : 0;

    const allTurns = this.listTurns(sessionId, targetBranch);
    const tailNodes = allTurns.filter(
      (node) => node.seq > lowerExclusive && node.seq <= ceiling && node.role !== "options",
    );

    const messages: StandaloneRawMessage[] = [];
    if (systemPrompt.trim()) {
      messages.push({ role: "system", content: systemPrompt.trim() });
    }
    if (checkpoint?.rollingSummary) {
      messages.push({
        role: "system",
        content: `【历史对话总结（截至第 ${checkpoint.upToSeq} 轮，供延续剧情与人物状态参考）】\n${checkpoint.rollingSummary}`,
      });
    }
    for (const node of tailNodes) {
      messages.push(cloneDeep(node.rawMessage));
    }

    return {
      checkpoint,
      messages,
      tailNodes,
    };
  }

  /**
   * Non-destructive rewind cascade:
   * Deletes TurnNodes with `seq > cutoffSeq` AND deletes CompactCheckpoints with `upToSeq > cutoffSeq`,
   * automatically falling back to any earlier valid CompactCheckpoint (`upToSeq <= cutoffSeq`).
   */
  async truncateAfter(sessionId: string, cutoffSeq: number, branchId?: string): Promise<TruncateResult> {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const bKey = this.branchMapKey(sessionId, targetBranch);

    const currentTurns = this.turnsBySessionBranch.get(bKey) ?? [];
    const keptTurns: TurnNode[] = [];
    const removedTurnKeys: string[] = [];
    for (const node of currentTurns) {
      if (node.seq <= cutoffSeq) {
        keptTurns.push(node);
      } else {
        removedTurnKeys.push(node.nodeKey);
      }
    }
    this.turnsBySessionBranch.set(bKey, keptTurns);

    const currentCheckpoints = this.checkpointsBySessionBranch.get(bKey) ?? [];
    const keptCheckpoints: CompactCheckpoint[] = [];
    const removedCheckpointKeys: string[] = [];
    for (const cp of currentCheckpoints) {
      if (cp.upToSeq <= cutoffSeq) {
        keptCheckpoints.push(cp);
      } else {
        removedCheckpointKeys.push(cp.checkpointKey);
      }
    }
    this.checkpointsBySessionBranch.set(bKey, keptCheckpoints);

    await Promise.all([
      idbDeleteMany("turn_nodes", removedTurnKeys),
      idbDeleteMany("compact_checkpoints", removedCheckpointKeys),
    ]);

    const survivingLastTurn = keptTurns.length ? cloneDeep(keptTurns[keptTurns.length - 1]) : null;
    const activeCheckpoint = keptCheckpoints.length
      ? cloneDeep(keptCheckpoints[keptCheckpoints.length - 1])
      : null;

    let restoredOutfits: StandaloneOutfitSnapshot | undefined;
    let restoredStage: StandaloneStageSnapshot | null | undefined;
    for (let i = keptTurns.length - 1; i >= 0; i -= 1) {
      if (!restoredOutfits && keptTurns[i].outfitSnapshot) {
        restoredOutfits = cloneDeep(keptTurns[i].outfitSnapshot);
      }
      if (restoredStage === undefined && keptTurns[i].stageSnapshot !== undefined) {
        restoredStage = cloneDeep(keptTurns[i].stageSnapshot);
      }
      if (restoredOutfits && restoredStage !== undefined) break;
    }

    const session = this.sessions.get(sessionId);
    if (session) {
      session.updatedAtMs = Date.now();
      session.preview = survivingLastTurn?.plainText.slice(0, 90) ?? "";
      if (restoredOutfits) {
        session.outfits = cloneDeep(restoredOutfits);
      }
      if (restoredStage?.stats) {
        session.stats = cloneDeep(restoredStage.stats);
      }
      await idbPut("sessions", session);
    }

    return {
      removedTurnCount: removedTurnKeys.length,
      removedCheckpointCount: removedCheckpointKeys.length,
      survivingLastTurn,
      activeCheckpoint,
      restoredOutfits,
      restoredStage,
    };
  }

  /**
   * Rewinds from the `userTurnIndex`-th user turn (0-indexed), deleting that user turn
   * and all subsequent turns/checkpoints, returning the removed user turn text.
   */
  async truncateFromUserTurnIndex(
    sessionId: string,
    userTurnIndex: number,
    branchId?: string,
  ): Promise<TruncateResult & { revertedUserText: string }> {
    const targetBranch = this.resolveBranchId(sessionId, branchId);
    const turns = this.listTurns(sessionId, targetBranch);
    const userNodes = turns.filter((node) => node.role === "user");
    if (userTurnIndex < 0 || userTurnIndex >= userNodes.length) {
      throw new Error(`Invalid userTurnIndex ${userTurnIndex} (available: ${userNodes.length})`);
    }
    const targetUserNode = userNodes[userTurnIndex];
    const cutoffSeq = targetUserNode.seq - 1;
    const result = await this.truncateAfter(sessionId, cutoffSeq, targetBranch);
    return {
      ...result,
      revertedUserText: targetUserNode.plainText,
    };
  }

  /**
   * Forks a new branch copying TurnNodes (`seq <= forkSeq`) and valid CompactCheckpoints (`upToSeq <= forkSeq`).
   */
  async forkBranch(
    sessionId: string,
    options?: {
      fromBranchId?: string;
      upToSeq?: number;
      branchId?: string;
      label?: string;
      switchActive?: boolean;
    },
  ): Promise<StandaloneBranchInfo> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }
    const sourceBranch = options?.fromBranchId ?? session.activeBranchId;
    const sourceTurns = this.listTurns(sessionId, sourceBranch);
    const forkSeq =
      options?.upToSeq ?? (sourceTurns.length ? sourceTurns[sourceTurns.length - 1].seq : 0);

    const now = Date.now();
    const newBranchId =
      options?.branchId ?? `branch-${Object.keys(session.branches).length + 1}-${now.toString(36)}`;
    const branchInfo: StandaloneBranchInfo = {
      branchId: newBranchId,
      label: options?.label ?? `分支 ${Object.keys(session.branches).length}`,
      parentBranchId: sourceBranch,
      forkedAtSeq: forkSeq,
      createdAtMs: now,
    };

    const clonedTurns = sourceTurns
      .filter((node) => node.seq <= forkSeq)
      .map<TurnNode>((node) => ({
        ...cloneDeep(node),
        branchId: newBranchId,
        nodeKey: makeNodeKey(sessionId, newBranchId, node.seq),
        turnId: `turn-${sessionId}-${newBranchId}-${node.seq}`,
      }));

    const sourceCheckpoints = this.listCheckpoints(sessionId, sourceBranch);
    const clonedCheckpoints = sourceCheckpoints
      .filter((cp) => cp.upToSeq <= forkSeq)
      .map<CompactCheckpoint>((cp) => ({
        ...cloneDeep(cp),
        branchId: newBranchId,
        checkpointKey: makeCheckpointKey(sessionId, newBranchId, cp.upToSeq),
        checkpointId: `cp-${sessionId}-${newBranchId}-${cp.upToSeq}-${now}`,
      }));

    this.turnsBySessionBranch.set(this.branchMapKey(sessionId, newBranchId), clonedTurns);
    this.checkpointsBySessionBranch.set(this.branchMapKey(sessionId, newBranchId), clonedCheckpoints);

    session.branches[newBranchId] = branchInfo;
    if (options?.switchActive !== false) {
      session.activeBranchId = newBranchId;
    }
    session.updatedAtMs = now;

    await Promise.all([
      idbPut("sessions", session),
      idbPutMany("turn_nodes", clonedTurns),
      idbPutMany("compact_checkpoints", clonedCheckpoints),
    ]);

    return cloneDeep(branchInfo);
  }
}
