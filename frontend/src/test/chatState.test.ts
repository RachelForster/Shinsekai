import { describe, expect, it } from "vitest";

import { chatStageReducer, emptyChatState } from "../features/chat-stage/chatState";

describe("chatStageReducer", () => {
  it("hydrates runtime snapshots from platform events", () => {
    const state = chatStageReducer(emptyChatState, {
      snapshot: {
        dialogText: "hello",
        inputDraft: "",
        options: ["继续"],
        sprites: [],
        status: "streaming",
      },
      type: "hydrate",
    });

    expect(state.dialogText).toBe("hello");
    expect(state.status).toBe("streaming");
    expect(state.options).toEqual(["继续"]);
  });

  it("keeps transient input draft local until submit", () => {
    const state = chatStageReducer(emptyChatState, { text: "draft", type: "setDraft" });
    expect(state.inputDraft).toBe("draft");
    expect(state.status).toBe("idle");
  });
});
