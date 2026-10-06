import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPanel } from "../../../features/agent/AgentPanel";
import { AgentDrawer } from "../../../features/agent/AgentDrawer";
import { createAgentPreviewPlatform } from "../../../shared/platform/agentPreviewPlatform";
import type { AgentPlatform, AgentTask } from "../../../shared/platform/agentTypes";
import { I18nProvider } from "../../../shared/i18n";

const mocks = vi.hoisted(() => ({ getPlatform: vi.fn() }));
vi.mock("../../../shared/platform/platform", () => ({ getPlatform: mocks.getPlatform }));
let api: AgentPlatform;

function renderPanel(drawer = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const wrap = (open = true) => (
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>{drawer ? <AgentDrawer onClose={vi.fn()} open={open} /> : <AgentPanel />}</MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>
  );
  const result = render(wrap());
  return { ...result, client, hide: () => result.rerender(wrap(false)), show: () => result.rerender(wrap(true)) };
}

describe("Agent conversation", () => {
  beforeEach(() => {
    api = createAgentPreviewPlatform();
    api.submitTask = vi.fn(api.submitTask);
    api.cancelTask = vi.fn(api.cancelTask);
    mocks.getPlatform.mockReturnValue({ agent: api });
  });

  it("creates one tab per session, selects new tabs, and preserves each draft", async () => {
    renderPanel();
    const create = await screen.findByRole("button", { name: "New session" });
    await waitFor(() => expect(create).toBeEnabled());
    fireEvent.click(create);
    const first = await screen.findByRole("tab", { name: "Session 1" });
    await waitFor(() => expect(first).toHaveAttribute("aria-selected", "true"));
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "first draft" } });
    fireEvent.click(create);
    const second = await screen.findByRole("tab", { name: "Session 2" });
    await waitFor(() => expect(second).toHaveAttribute("aria-selected", "true"));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "second draft" } });
    fireEvent.click(first);
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("first draft");
    fireEvent.click(second);
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("second draft");
    fireEvent.click(screen.getByRole("button", { name: "Close Session 2" }));
    await waitFor(() => expect(screen.queryByRole("tab", { name: "Session 2" })).not.toBeInTheDocument());
    expect(first).toHaveAttribute("aria-selected", "true");
  });

  it("retries a lost acceptance response with the same request ID", async () => {
    await api.createSession();
    const submit = api.submitTask;
    let first = true;
    api.submitTask = vi.fn(async (...args: Parameters<AgentPlatform["submitTask"]>) => {
      const receipt = await submit(...args);
      if (first) {
        first = false;
        throw new Error("Lost response");
      }
      return receipt;
    });
    renderPanel();
    await screen.findByRole("tab", { name: "Session 1" });
    const input = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(input, { target: { value: "one logical message" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Lost response");
    await screen.findByText("Completed");
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(input).toHaveValue(""));
    const calls = vi.mocked(api.submitTask).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0][1].requestId).toBe(calls[1][1].requestId);
    expect((await api.listTasks(calls[0][0])).tasks).toHaveLength(1);
  });

  it("shows an accepted stop as the eventual cancelled task status", async () => {
    await api.createSession();
    renderPanel();
    await screen.findByRole("tab", { name: "Session 1" });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "a task to stop" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(api.cancelTask).toHaveBeenCalledTimes(1);
  });

  it.each(["question", "confirmation"] as const)(
    "answers a recovered %s without treating it as a chat message",
    async (kind) => {
      const session = await api.createSession();
      let status: AgentTask["status"] = "waiting_input";
      const task: AgentTask = {
        taskId: "task-input",
        sessionId: session.sessionId,
        requestId: "previous",
        input: { text: "previous question" },
        status,
        createdAt: "2026-10-06T00:00:00Z",
        updatedAt: "2026-10-06T00:00:00Z",
        result: null,
        error: null,
      };
      api.listTasks = vi.fn(async () => ({ tasks: [{ ...task, status }], nextCursor: null }));
      api.readEvents = vi.fn(async (_, afterSeq) => ({
        taskId: task.taskId,
        events: afterSeq
          ? []
          : [
              {
                taskId: task.taskId,
                eventSeq: 1,
                schemaVersion: 1,
                timestamp: task.createdAt,
                type: "input.requested",
                payload: {
                  inputRequestId: "input-1",
                  kind,
                  question: "Choose a path",
                  options: kind === "question" ? [{ value: "safe", label: "Safe option" }] : [],
                  expiresAt: "2099-01-01T00:00:00Z",
                },
              },
            ],
        nextSeq: 1,
      }));
      api.respondInput = vi.fn(async () => {
        status = "running";
        return { ...task, status };
      });
      renderPanel();
      const prompt = await screen.findByRole("region", { name: "Your answer is needed" });
      fireEvent.click(within(prompt).getByRole("button", { name: kind === "question" ? "Safe option" : "Confirm" }));
      await waitFor(() =>
        expect(api.respondInput).toHaveBeenCalledWith(task.taskId, {
          inputRequestId: "input-1",
          value: kind === "question" ? "safe" : true,
        }),
      );
      expect(api.submitTask).not.toHaveBeenCalled();
    },
  );

  it("closing and reopening the drawer keeps drafts and never cancels work", async () => {
    await api.createSession();
    const view = renderPanel(true);
    await screen.findByRole("tab", { name: "Session 1" });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "keep this draft" } });
    view.hide();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    view.show();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("keep this draft");
    expect(api.cancelTask).not.toHaveBeenCalled();
  });

  it("recovers native progress alongside streaming reply text", async () => {
    const session = await api.createSession();
    const timestamp = new Date().toISOString();
    const task: AgentTask = {
      taskId: "progress-task",
      sessionId: session.sessionId,
      requestId: "previous",
      input: { text: "inspect the character" },
      status: "running",
      createdAt: timestamp,
      updatedAt: timestamp,
      result: null,
      error: null,
    };
    api.listTasks = vi.fn(async () => ({ tasks: [task], nextCursor: null }));
    api.readEvents = vi.fn(async (_, afterSeq) => ({
      taskId: task.taskId,
      nextSeq: 2,
      events: afterSeq
        ? []
        : [
            {
              taskId: task.taskId,
              schemaVersion: 1,
              timestamp,
              eventSeq: 1,
              type: "message.delta",
              payload: { messageId: "reply", delta: "Checking your files." },
            },
            {
              taskId: task.taskId,
              schemaVersion: 1,
              timestamp,
              eventSeq: 2,
              type: "activity.updated",
              payload: {
                activityId: "attempt:call",
                kind: "tool",
                name: "powershell",
                status: "running",
                target: "Get-Content character.json",
              },
            },
          ],
    }));
    const result = renderPanel(true);
    expect(await screen.findByText("Checking your files.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Running a command"));
    expect(screen.getByRole("status")).toHaveTextContent("Get-Content character.json");
    result.hide();
    result.show();
    expect(screen.getByRole("status")).toHaveTextContent("Get-Content character.json");
  });
});
