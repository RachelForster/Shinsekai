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

  it("replays interleaved native activity and host tools without duplicates or losing timestamps", () => {
    const event = { taskId: "task", schemaVersion: 1, timestamp: "2026-10-06T00:00:00Z" };
    const page: AgentEventPage = {
      taskId: "task",
      nextSeq: 2,
      events: [
        {
          ...event,
          eventSeq: 1,
          type: "activity.updated",
          payload: {
            activityId: "attempt:call",
            kind: "tool",
            name: "read",
            status: "running",
            target: "/skills/guide/SKILL.md",
          },
        },
        {
          ...event,
          eventSeq: 2,
          type: "tool.started",
          payload: {
            call: {
              callId: "call",
              name: "shinsekai.bridge.read",
              arguments: { operation: "characters.get", params: { name: "Alice" } },
            },
          },
        },
      ],
    };
    const first = mergeAgentEvents(emptyTranscript("task"), page);
    const replay = mergeAgentEvents(first, page);
    expect(replay.activities).toHaveLength(2);
    const end = "2026-10-06T00:00:05Z";
    const finished = mergeAgentEvents(replay, {
      taskId: "task",
      nextSeq: 4,
      events: [
        {
          ...event,
          timestamp: end,
          eventSeq: 3,
          type: "activity.updated",
          payload: {
            activityId: "attempt:call",
            kind: "tool",
            name: "read",
            status: "succeeded",
            target: "/skills/guide/SKILL.md",
          },
        },
        {
          ...event,
          timestamp: end,
          eventSeq: 4,
          type: "tool.completed",
          payload: { result: { callId: "call", ok: false, error: { message: "not found" } } },
        },
      ],
    });
    expect(finished.activities.map(({ name, target, status }) => ({ name, target, status }))).toEqual([
      { name: "read", target: "/skills/guide/SKILL.md", status: "succeeded" },
      { name: "characters.get", target: "Alice", status: "failed" },
    ]);
    expect(finished.activities[0].startedAt).toBe(event.timestamp);
    expect(finished.activities[0].updatedAt).toBe(end);
    expect(first.activities.every((activity) => activity.status === "running")).toBe(true);
    expect(first.tools[0].result).toBeUndefined();
  });
});
