import { describe, expect, it } from "vitest";

import { CHAT_ATTACHMENT_LIMIT } from "../../../features/chat-stage/attachments";
import { emptyChatState } from "../../../features/chat-stage/chatState";
import {
  chatRouteInputState,
  initialChatStageState,
  withChatRouteInputState,
} from "../../../features/chat-stage/controllers/chatStageRouteState";

describe("chatStageRouteState", () => {
  it("returns empty input state when route state is missing or malformed", () => {
    expect(chatRouteInputState(undefined)).toEqual({ inputAttachments: [], inputDraft: "" });
    expect(chatRouteInputState(null)).toEqual({ inputAttachments: [], inputDraft: "" });
    expect(chatRouteInputState("bad")).toEqual({ inputAttachments: [], inputDraft: "" });
    expect(chatRouteInputState({ chatInput: null })).toEqual({ inputAttachments: [], inputDraft: "" });
    expect(chatRouteInputState({ chatInput: { inputAttachments: "bad", inputDraft: 123 } })).toEqual({
      inputAttachments: [],
      inputDraft: "",
    });
  });

  it("filters invalid attachments, clones entries, and enforces attachment limit", () => {
    const attachments = Array.from({ length: CHAT_ATTACHMENT_LIMIT + 3 }, (_, index) => ({
      kind: index % 2 === 0 ? ("image" as const) : ("file" as const),
      name: `file-${index}.png`,
      path: `/tmp/file-${index}.png`,
    }));
    const source = {
      chatInput: {
        inputAttachments: [
          null,
          { kind: "video", name: "bad.mp4", path: "/tmp/bad.mp4" },
          { kind: "image", name: 42, path: "/tmp/noname.png" },
          ...attachments,
        ],
        inputDraft: "hello stage",
      },
    };

    const parsed = chatRouteInputState(source);
    expect(parsed.inputDraft).toBe("hello stage");
    expect(parsed.inputAttachments).toHaveLength(CHAT_ATTACHMENT_LIMIT);
    expect(parsed.inputAttachments[0]).toEqual(attachments[0]);
    expect(parsed.inputAttachments[0]).not.toBe(attachments[0]);
  });

  it("initializes stage state and writes route state without dropping sibling keys", () => {
    const attachment = { kind: "image" as const, name: "pic.png", path: "/tmp/pic.png" };
    const stageState = initialChatStageState({
      chatInput: { inputAttachments: [attachment], inputDraft: "draft" },
    });
    expect(stageState).toEqual({
      ...emptyChatState,
      inputAttachments: [attachment],
      inputDraft: "draft",
    });

    const nextRouteState = withChatRouteInputState(
      { from: "templates", keepFlag: true },
      { inputAttachments: [attachment], inputDraft: "updated" },
    );
    expect(nextRouteState).toEqual({
      from: "templates",
      keepFlag: true,
      chatInput: {
        inputAttachments: [attachment],
        inputDraft: "updated",
      },
    });
    expect((nextRouteState.chatInput as { inputAttachments: unknown[] }).inputAttachments[0]).not.toBe(attachment);

    expect(withChatRouteInputState(["ignored"], { inputAttachments: [], inputDraft: "clean" })).toEqual({
      chatInput: { inputAttachments: [], inputDraft: "clean" },
    });
  });
});
