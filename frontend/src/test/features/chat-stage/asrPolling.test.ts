import { describe, expect, it } from "vitest";
import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";

function snapshot(inputDraft: string, eventSeq: number) {
  return { ...emptyChatState, sessionId: "normal-session", effectImage: null, inputDraft, eventSeq };
}

describe("ordinary ASR polling recovery", () => {
  it("updates partials and clears accepted speech when the final event was missed", () => {
    const first = chatStageReducer(emptyChatState, { type: "hydrate", snapshot: snapshot("我", 1) });
    const next = chatStageReducer(first, { type: "hydrate", snapshot: snapshot("我喜欢室内活动", 2) });
    expect(next.inputDraft).toBe("我喜欢室内活动");
    const consumed = chatStageReducer(next, { type: "hydrate", snapshot: snapshot("", 3) });
    expect(consumed.inputDraft).toBe("");
    expect(chatStageReducer(consumed, { type: "hydrate", snapshot: snapshot("下一句", 4) }).inputDraft).toBe("下一句");
  });
  it("preserves a manual edit when the server consumes the previous ASR result", () => {
    const asr = chatStageReducer(emptyChatState, { type: "hydrate", snapshot: snapshot("语音", 1) });
    const edited = chatStageReducer(asr, { type: "setDraft", text: "手动补充" });
    expect(chatStageReducer(edited, { type: "hydrate", snapshot: snapshot("", 2) }).inputDraft).toBe("手动补充");
  });
  it("clears live partials when reconnecting to an empty authoritative snapshot", () => {
    const partial = chatStageReducer(emptyChatState, {
      type: "event",
      event: {
        type: "asr.partial",
        text: "语音",
        seq: 1,
        ts: 1,
        v: 1,
      },
    });
    expect(chatStageReducer(partial, { type: "hydrate", snapshot: snapshot("", 2) }).inputDraft).toBe("");
  });
  it("preserves manual edits made after a rejected optimistic submission", () => {
    let state = chatStageReducer(emptyChatState, { type: "hydrate", snapshot: snapshot("语音", 1) });
    state = chatStageReducer(state, { type: "submitUserMessage", text: "语音" });
    state = chatStageReducer(state, { type: "setDraft", text: "补充" });
    state = chatStageReducer(state, { type: "rollbackUserSubmission", source: "send-message" });
    expect(chatStageReducer(state, { type: "hydrate", snapshot: snapshot("", 2) }).inputDraft).toBe("补充");
  });
});
