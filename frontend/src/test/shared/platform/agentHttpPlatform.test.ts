import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpPlatform } from "../../../shared/platform/httpPlatform";

afterEach(() => vi.unstubAllGlobals());

describe("Agent HTTP transport", () => {
  it("uses the existing authenticated transport and sends only the message contract", async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ taskId: "task", status: "queued" }) }));
    vi.stubGlobal("fetch", fetch);
    const platform = createHttpPlatform("http://127.0.0.1:8787", "private-bridge-token");
    await platform.agent.submitTask("session/id", { requestId: "request", text: "hello" });
    expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8787/api/agent/sessions/session%2Fid/tasks",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Shinsekai-Bridge-Token": "private-bridge-token" }),
        body: JSON.stringify({ requestId: "request", text: "hello" }),
      }),
    );
    const signal = new AbortController().signal;
    await platform.agent.readEvents("task", 42, signal);
    expect(fetch).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8787/api/agent/tasks/task/events?afterSeq=42&limit=1000",
      expect.objectContaining({
        signal,
        headers: expect.objectContaining({ "X-Shinsekai-Bridge-Token": "private-bridge-token" }),
      }),
    );
  });

  it("preserves portable Agent error codes for UI recovery", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        status: 409,
        json: async () => ({ error: "Session is busy", errorCode: "SESSION_BUSY" }),
      })),
    );
    await expect(
      createHttpPlatform("http://127.0.0.1:8787", "token").agent.closeSession("session"),
    ).rejects.toMatchObject({ errorCode: "SESSION_BUSY", status: 409 });
  });
});
