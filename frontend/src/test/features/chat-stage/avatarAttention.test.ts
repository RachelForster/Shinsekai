import { describe, expect, it } from "vitest";
import {
  buildChatStageViewModel,
  chatStageReducer,
  emptyChatState,
  type ChatStageState,
} from "../../../features/chat-stage/chatState";

const sprite = (name: string) => ({
  id: name,
  label: name,
  path: `/${name}.json`,
  avatarType: "mmd",
  modelUrl: `/${name}.pmx`,
});
function submitted(names: string[], previous?: string, queued = false) {
  const state: ChatStageState = {
    ...emptyChatState,
    sprites: names.map(sprite),
    characterName: previous,
    dialogText: "Previous reply",
    userDisplayName: "You",
  };
  return chatStageReducer(state, { type: "submitUserMessage", text: "Hello", queued });
}
const target = (state: ChatStageState) => buildChatStageViewModel(state).thinkingCharacterName;

describe("conversation attention target", () => {
  it("uses the previous visible speaker in a group and never picks the first slot arbitrarily", () => {
    expect(target(submitted(["Alice", "Bob", "Carol"], "Bob"))).toBe("Bob");
    expect(target(submitted(["Alice", "Bob"], undefined))).toBeUndefined();
    expect(target(submitted(["Alice", "Bob"], "off-stage"))).toBeUndefined();
    expect(target(submitted(["Alice", "Bob"], "You"))).toBeUndefined();
  });
  it("can identify a solo character without a previous reply, including a submitted option", () => {
    expect(target(submitted(["Alice"]))).toBe("Alice");
    const state = chatStageReducer(
      { ...emptyChatState, sprites: [sprite("Alice")] },
      {
        type: "submitUserMessage",
        source: "submit-option",
        text: "Yes",
      },
    );
    expect(target(state)).toBe("Alice");
  });
  it("ends the thought on reply, cancellation, error, rollback or session close", () => {
    const pending = submitted(["Alice", "Bob"], "Bob");
    expect(target({ ...pending, characterName: "Alice" })).toBeUndefined();
    for (const status of ["idle", "streaming", "speaking", "paused", "error"] as const)
      expect(target({ ...pending, status })).toBeUndefined();
    expect(target({ ...pending, error: "Network error" })).toBeUndefined();
    expect(target({ ...pending, sessionClosedReason: "Closed" })).toBeUndefined();
    expect(
      target(chatStageReducer(pending, { type: "rollbackUserSubmission", source: "send-message" })),
    ).toBeUndefined();
    expect(
      target(
        chatStageReducer(pending, {
          type: "event",
          event: {
            type: "dialog.end",
            speaker: "Alice",
            fullHtml: "Reply",
            isSystem: false,
            color: "",
            seq: 1,
            ts: 1,
            v: 1,
          },
        }),
      ),
    ).toBeUndefined();
    expect(
      target(
        chatStageReducer(pending, {
          type: "event",
          event: {
            type: "reply.finished",
            seq: 1,
            ts: 1,
            v: 1,
          },
        }),
      ),
    ).toBeUndefined();
  });
  it("waits for queued messages to be processed and ignores unrelated generation", () => {
    const pending = submitted(["Alice"], "Alice", true);
    expect(target(pending)).toBeUndefined();
    expect(target({ ...pending, status: "generating" })).toBe("Alice");
    expect(target({ ...emptyChatState, status: "generating", sprites: [sprite("Alice")] })).toBeUndefined();
  });
});
