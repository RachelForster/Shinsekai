import { beforeEach, describe, expect, it } from "vitest";

import { clearAllStandaloneStorage } from "../../../../shared/platform/standalone/storage/indexedDbStore";
import { StandaloneSessionStore } from "../../../../shared/platform/standalone/storage/sessionStore";

describe("StandaloneSessionStore", () => {
  beforeEach(async () => {
    await clearAllStandaloneStorage();
  });

  it("keeps full raw history immutable across multiple compaction checkpoints and cascades truncateAfter", async () => {
    const store = new StandaloneSessionStore();
    await store.hydrate();

    const session = await store.ensureSession({
      sessionId: "s-1",
      historyPath: "./data/history/s-1.json",
      title: "测试剧情",
      payload: {
        templateId: "tpl-1",
        characters: ["星奈"],
        backgroundName: "星海观测台",
        historyPath: "./data/history/s-1.json",
      },
      outfits: {
        星奈: { characterName: "星奈", activeGroup: "常服", locked: false },
      },
    });

    // Append 6 turns (3 user + 3 assistant), changing outfit & background at turn 4
    await store.appendTurn(session.sessionId, {
      role: "user",
      plainText: "第1句：你好星奈",
      outfitSnapshot: { 星奈: { characterName: "星奈", activeGroup: "常服", locked: false } },
      stageSnapshot: { backgroundPath: "bg-1.png", bgmPath: "", cgPath: "", sprites: [], stats: [{ icon: "heart", label: "好感度", value: 10 }] },
    });
    await store.appendTurn(session.sessionId, {
      role: "assistant",
      speaker: "星奈",
      plainText: "第2句：欢迎来到观测台",
      outfitSnapshot: { 星奈: { characterName: "星奈", activeGroup: "常服", locked: false } },
      stageSnapshot: { backgroundPath: "bg-1.png", bgmPath: "", cgPath: "", sprites: [], stats: [{ icon: "heart", label: "好感度", value: 15 }] },
    });
    await store.saveCompactCheckpoint(session.sessionId, {
      upToSeq: 2,
      rollingSummary: "早期的相遇与自我介绍。",
    });

    await store.appendTurn(session.sessionId, {
      role: "user",
      plainText: "第3句：换件礼服看看吧",
      outfitSnapshot: { 星奈: { characterName: "星奈", activeGroup: "常服", locked: false } },
    });
    await store.appendTurn(session.sessionId, {
      role: "assistant",
      speaker: "星奈",
      plainText: "第4句：换好了，怎么样？",
      outfitSnapshot: { 星奈: { characterName: "星奈", activeGroup: "礼服", locked: false } },
      stageSnapshot: { backgroundPath: "bg-2.png", bgmPath: "", cgPath: "", sprites: [], stats: [{ icon: "heart", label: "好感度", value: 30 }] },
    });
    await store.saveCompactCheckpoint(session.sessionId, {
      upToSeq: 4,
      rollingSummary: "两人初遇并一起在观测台试穿礼服。",
    });

    await store.appendTurn(session.sessionId, {
      role: "user",
      plainText: "第5句：去天台看星星吧",
    });
    await store.appendTurn(session.sessionId, {
      role: "assistant",
      speaker: "星奈",
      plainText: "第6句：今晚的流星真亮！",
      outfitSnapshot: { 星奈: { characterName: "星奈", activeGroup: "礼服", locked: false } },
      stageSnapshot: { backgroundPath: "bg-roof.png", bgmPath: "", cgPath: "", sprites: [], stats: [{ icon: "heart", label: "好感度", value: 45 }] },
    });

    // Full raw messages stay 100% intact for UI/replay
    const fullRaw = store.buildFullRawMessages(session.sessionId);
    expect(fullRaw).toHaveLength(6);
    expect(fullRaw[0].content).toContain("你好星奈");
    expect(fullRaw[5].content).toContain("今晚的流星真亮");

    // Active LLM view projects [system, checkpoint@4, tail(5,6)]
    const activeView = store.buildActiveLlmMessages(session.sessionId, "SYS");
    expect(activeView.checkpoint?.upToSeq).toBe(4);
    expect(activeView.tailNodes.map((n) => n.seq)).toEqual([5, 6]);
    expect(activeView.messages).toHaveLength(4);
    expect(activeView.messages[1].content).toContain("试穿礼服");

    // Rewind to before userTurnIndex 1 ("第3句：换件礼服看看吧", seq=3) -> cutoffSeq=2
    // Checkpoint@4 MUST be cascade-deleted while Checkpoint@2 survives, restoring outfit "常服" & bg-1
    const rewind = await store.truncateFromUserTurnIndex(session.sessionId, 1);
    expect(rewind.revertedUserText).toBe("第3句：换件礼服看看吧");
    expect(rewind.removedCheckpointCount).toBe(1);
    expect(rewind.activeCheckpoint?.upToSeq).toBe(2);
    expect(rewind.restoredOutfits?.["星奈"]?.activeGroup).toBe("常服");
    expect(rewind.restoredStage?.backgroundPath).toBe("bg-1.png");

    const afterRewindView = store.buildActiveLlmMessages(session.sessionId, "SYS");
    expect(afterRewindView.checkpoint?.upToSeq).toBe(2);
    expect(afterRewindView.messages[1].content).toContain("早期的相遇");
    expect(store.buildFullRawMessages(session.sessionId)).toHaveLength(2);
  });

  it("forks branches preserving isolated turns and checkpoints", async () => {
    const store = new StandaloneSessionStore();
    await store.hydrate();
    const session = await store.ensureSession({
      sessionId: "s-fork",
      historyPath: "./data/history/s-fork.json",
      title: "分支测试",
      payload: {
        templateId: "tpl",
        characters: ["星奈"],
        backgroundName: "观测台",
        historyPath: "./data/history/s-fork.json",
      },
    });

    await store.appendTurn(session.sessionId, { role: "user", plainText: "A1" });
    await store.appendTurn(session.sessionId, { role: "assistant", speaker: "星奈", plainText: "A2" });
    await store.saveCompactCheckpoint(session.sessionId, { upToSeq: 2, rollingSummary: "主线总结" });
    await store.appendTurn(session.sessionId, { role: "user", plainText: "A3" });

    const branch = await store.forkBranch(session.sessionId, {
      fromBranchId: "main",
      upToSeq: 2,
      branchId: "route-b",
      label: "B线",
    });
    expect(branch.branchId).toBe("route-b");

    await store.appendTurn(session.sessionId, { role: "user", plainText: "B3" }, "route-b");
    expect(store.listTurns(session.sessionId, "main").map((n) => n.plainText)).toEqual(["A1", "A2", "A3"]);
    expect(store.listTurns(session.sessionId, "route-b").map((n) => n.plainText)).toEqual(["A1", "A2", "B3"]);
    expect(store.getLatestCheckpoint(session.sessionId, "route-b")?.rollingSummary).toBe("主线总结");
  });
});
