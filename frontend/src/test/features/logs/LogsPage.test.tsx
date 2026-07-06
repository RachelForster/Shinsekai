import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LogsPage } from "../../../features/logs/LogsPage";
import type { LogFileList, LogSnapshot } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mockGetDefaultLog = vi.fn();
const mockListLogFiles = vi.fn();
const mockReadLog = vi.fn();
const mockImportLog = vi.fn();
const mockExportDiagnosticBundle = vi.fn();

vi.mock("../../../entities/logs/repository", () => ({
  exportDiagnosticBundle: () => mockExportDiagnosticBundle(),
  getDefaultLog: () => mockGetDefaultLog(),
  importLog: (files: File[] | string[]) => mockImportLog(files),
  listLogFiles: () => mockListLogFiles(),
  logFilesQueryKey: ["logs", "files"],
  logsQueryKey: ["logs", "default"],
  readLog: (path: string) => mockReadLog(path),
}));

const defaultLog: LogSnapshot = {
  content: [
    JSON.stringify({
      duration_ms: 42,
      event: "chat.failed",
      level: "error",
      logger: "chat.engine",
      message: "Boom",
      plugin_id: "choices",
      task_id: "task-7",
      timestamp: "2026-01-02T03:04:05.000Z",
    }),
    "12:00:01 [Info] updater update.started url=http://example.test ok",
    "[restart-debug] ts=12:00:02 component=watcher phase=spawn ready=true",
    "plain line with warning text",
  ].join("\n"),
  modifiedAt: 1_750_000_000,
  name: "app.log",
  path: "/logs/app.log",
  size: 2048,
  truncated: true,
};

const logFiles: LogFileList = {
  files: [
    {
      modifiedAt: 1_750_000_010,
      name: "worker.log",
      path: "/logs/worker.log",
      relativePath: "runtime/worker.log",
      size: 512,
    },
    {
      modifiedAt: 1_750_000_000,
      name: "app.log",
      path: "/logs/app.log",
      relativePath: "runtime/app.log",
      size: 2048,
    },
  ],
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <LogsPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function selectComboboxOption(name: string, option: string) {
  fireEvent.click(screen.getByRole("combobox", { name }));
  fireEvent.click(screen.getByRole("option", { name: option }));
}

describe("LogsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDefaultLog.mockResolvedValue(structuredClone(defaultLog));
    mockListLogFiles.mockResolvedValue(structuredClone(logFiles));
    mockReadLog.mockImplementation(async (path: string) => ({
      content: "09:30:00 [Warn] worker job.retry task_id=task-9 reason=timeout",
      modifiedAt: 1_750_000_020,
      name: "worker.log",
      path,
      size: 128,
    }));
    mockImportLog.mockResolvedValue({
      content: '{"level":"info","logger":"importer","message":"Imported ok"}',
      modifiedAt: 1_750_000_030,
      name: "manual.log",
      path: "/tmp/manual.log",
      size: 64,
    });
    mockExportDiagnosticBundle.mockResolvedValue({
      downloadUrl: "https://example.test/diagnostics.zip",
      path: "/tmp/diagnostics.zip",
    });
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  it("renders structured lines, expands details, and filters by level and search text", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "运行日志" })).toBeInTheDocument();
    expect(await screen.findByText("Boom")).toBeInTheDocument();
    const viewer = screen.getByLabelText("日志内容");
    expect(screen.getAllByText("app.log").length).toBeGreaterThan(0);
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.getByText("当前仅显示日志尾部内容。")).toBeInTheDocument();
    expect(within(viewer).getByText("chat.failed")).toBeInTheDocument();
    expect(within(viewer).getByText("plugin choices")).toBeInTheDocument();
    expect(within(viewer).getByText("task task-7")).toBeInTheDocument();
    expect(within(viewer).getByText("update.started")).toBeInTheDocument();
    expect(within(viewer).getByText("restart-debug")).toBeInTheDocument();

    fireEvent.click(within(viewer).getByText("展开"));
    expect(within(viewer).getByText("duration_ms")).toBeInTheDocument();
    expect(within(viewer).getByText("42")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索日志"), { target: { value: "Boom" } });
    expect(within(viewer).getByText("Boom")).toBeInTheDocument();
    expect(within(viewer).queryByText("update.started")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索日志"), { target: { value: "" } });
    selectComboboxOption("日志级别", "Debug");
    expect(within(viewer).getByText("restart-debug")).toBeInTheDocument();
    expect(within(viewer).queryByText("Boom")).not.toBeInTheDocument();

    selectComboboxOption("日志级别", "全部级别");
    selectComboboxOption("Logger", "chat.engine");
    expect(within(viewer).getByText("Boom")).toBeInTheDocument();
    expect(within(viewer).queryByText("restart-debug")).not.toBeInTheDocument();
  });

  it("loads recent logs, imports a local file, and opens the diagnostic bundle", async () => {
    const { container } = renderPage();

    expect(await screen.findByText("runtime/worker.log")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /runtime\/worker\.log/ }));

    await waitFor(() => expect(mockReadLog).toHaveBeenCalledWith("/logs/worker.log"));
    expect(await within(screen.getByLabelText("日志内容")).findByText("job.retry")).toBeInTheDocument();
    expect(screen.getAllByText("worker.log").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "诊断包" }));
    await waitFor(() => expect(mockExportDiagnosticBundle).toHaveBeenCalledTimes(1));
    expect(window.open).toHaveBeenCalledWith("https://example.test/diagnostics.zip", "_blank", "noopener,noreferrer");

    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const file = new File(["manual"], "manual.log", { type: "text/plain" });
    fireEvent.change(input!, { target: { files: [file] } });

    await waitFor(() => expect(mockImportLog).toHaveBeenCalledWith([file]));
    expect(await screen.findByText("Imported ok")).toBeInTheDocument();
    expect(screen.getAllByText("manual.log").length).toBeGreaterThan(0);
  });

  it("shows retryable default-log errors while still rendering file list failures", async () => {
    mockGetDefaultLog
      .mockRejectedValueOnce(new Error("default missing"))
      .mockRejectedValueOnce(new Error("default missing"))
      .mockResolvedValueOnce(structuredClone(defaultLog));
    mockListLogFiles.mockRejectedValueOnce(new Error("list failed")).mockRejectedValueOnce(new Error("list failed"));
    renderPage();

    expect(await screen.findByText("无法读取默认日志", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText("default missing")).toBeInTheDocument();
    expect(screen.getByText("日志列表读取失败。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => expect(mockGetDefaultLog).toHaveBeenCalledTimes(3));
  });
});
