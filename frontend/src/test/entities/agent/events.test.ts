import { describe, expect, it } from "vitest";
import { emptyTranscript, mergeAgentEvents } from "../../../entities/agent/events";
import type { AgentEventPage } from "../../../shared/platform/agentTypes";

describe("Agent persisted events", () => {
  it("deduplicates replayed deltas and replaces them with authoritative completed text", () => {
    const event = { taskId: "task", schemaVersion: 1, timestamp: "2026-10-06T00:00:00Z" };
    const page: AgentEventPage = {
      taskId: "task",
      nextSeq: 2,
      events: [
        { ...event, eventSeq: 1, type: "message.delta", payload: { messageId: "m", delta: "hel" } },
        { ...event, eventSeq: 2, type: "message.delta", payload: { messageId: "m", delta: "lo" } },
      ],
    };
    const initial = emptyTranscript("task");
    const first = mergeAgentEvents(initial, page);
    const replay = mergeAgentEvents(first, page);
    expect(replay.messages[0].text).toBe("hello");
    expect(initial.messages).toEqual([]);
    const completed = mergeAgentEvents(replay, {
      taskId: "task",
      nextSeq: 3,
      events: [{ ...event, eventSeq: 3, type: "message.completed", payload: { messageId: "m", text: "final text" } }],
    });
    expect(completed.messages).toEqual([{ id: "m", text: "final text", complete: true }]);
  });

  it("advances past unknown events, retains cursors, and rejects another task's page", () => {
    const initial = emptyTranscript("task");
    const next = mergeAgentEvents(initial, { taskId: "task", events: [], nextSeq: 50 });
    expect(next.nextSeq).toBe(50);
    expect(mergeAgentEvents(next, { taskId: "other", events: [], nextSeq: 100 })).toBe(next);
    expect(mergeAgentEvents(next, { taskId: "task", events: [], nextSeq: 0 }).nextSeq).toBe(50);
  });
});
