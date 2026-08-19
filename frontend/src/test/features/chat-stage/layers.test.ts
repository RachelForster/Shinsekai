import { describe, expect, it } from "vitest";

import { optionsHeldForDialog } from "../../../features/chat-stage/state/layers";
import type { ChatStageState } from "../../../features/chat-stage/state/types";

function state(overrides: Partial<ChatStageState>): ChatStageState {
  return {
    characterName: "绫",
    dialogText: "房间里有一排尚未检查的柜子。",
    options: ["检查柜子", "询问绫"],
    status: "idle",
    userDisplayName: "用户",
    ...overrides,
  } as ChatStageState;
}

describe("optionsHeldForDialog", () => {
  it.each(["generating", "streaming", "speaking"] as const)(
    "holds LLM-authored options while the reply is %s",
    (status) => {
      expect(optionsHeldForDialog(state({ status }))).toBe(true);
    },
  );

  it("shows LLM-authored options after the reply is complete", () => {
    expect(optionsHeldForDialog(state({ status: "idle" }))).toBe(false);
  });
});
