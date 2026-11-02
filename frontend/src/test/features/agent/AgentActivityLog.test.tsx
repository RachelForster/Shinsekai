import { act, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentActivityLog } from "../../../features/agent/AgentActivityLog";
import { emptyTranscript, type AgentActivityEntry } from "../../../entities/agent/events";
import type { AgentTask } from "../../../shared/platform/agentTypes";
import { I18nProvider } from "../../../shared/i18n";

const task: AgentTask = {
  taskId: "task",
  sessionId: "session",
  requestId: "request",
  input: { text: "create a character" },
  status: "running",
  createdAt: "2026-10-06T00:00:00Z",
  updatedAt: "2026-10-06T00:00:10Z",
  result: null,
  error: null,
};
const activity: AgentActivityEntry = {
  activityId: "native:call",
  kind: "tool",
  name: "read",
  status: "running",
  target: "C:\\session\\skills\\shinsekai-guide\\SKILL.md",
  startedAt: task.createdAt,
  updatedAt: task.createdAt,
  eventSeq: 1,
};

function view(value = task, entry = activity) {
  return (
    <I18nProvider language="en">
      <AgentActivityLog task={value} enabled transcript={{ ...emptyTranscript("task"), activities: [entry] }} />
    </I18nProvider>
  );
}

describe("Agent activity", () => {
  afterEach(() => vi.useRealTimers());

  it("shows a skill being read and updates its elapsed time while running", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-06T00:00:05Z"));
    render(view());
    const current = screen.getByRole("status");
    expect(current).toHaveTextContent("Reading a skill");
    expect(current).toHaveTextContent("shinsekai-guide");
    expect(current).toHaveTextContent("5s");
    act(() => vi.advanceTimersByTime(1000));
    expect(current).toHaveTextContent("6s");
    expect(screen.getByText("Activity · 1 steps").closest("details")).toHaveAttribute("open");
  });

  it("keeps interrupted calls distinguishable from success when a task finishes", () => {
    const result = render(view());
    result.rerender(view({ ...task, status: "interrupted" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("Activity · 1 steps").closest("details")).not.toHaveAttribute("open");
    const step = screen.getByRole("listitem");
    expect(step).toHaveTextContent("Interrupted · 10s");
    expect(step).not.toHaveTextContent("Completed");
    result.rerender(view({ ...task, status: "cancelled" }));
    expect(step).toHaveTextContent("Stopped · 10s");
  });

  it("keeps the current command visible after reply text starts and handles waiting input", () => {
    const entry = { ...activity, name: "powershell", target: "Get-Content -LiteralPath 'character.json'" };
    const result = render(view(task, entry));
    expect(within(screen.getByRole("status")).getByText("Running a command")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(entry.target);
    result.rerender(view({ ...task, status: "waiting_input" }, entry));
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for your answer");
    expect(screen.getByRole("status")).not.toHaveTextContent(entry.target);
  });

  it("shows native failure even if the model subsequently recovers", () => {
    render(view({ ...task, status: "succeeded" }, { ...activity, status: "failed", updatedAt: task.updatedAt }));
    expect(screen.getByRole("listitem")).toHaveTextContent("Failed · 10s");
  });
});
