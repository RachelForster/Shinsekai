/// <reference types="vitest/jsdom" />

import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as perceptionRepo from "../../../entities/perception/repository";
import { ChatStagePage } from "../../../features/chat-stage/ChatStagePage";
import { ScreenSharePreflightDialog } from "../../../features/chat-stage/components/ScreenSharePreflightDialog";
import { useScreenSharePreflight } from "../../../features/chat-stage/hooks/useScreenSharePreflight";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type {
  PerceptionLocalServerStatus,
  PerceptionStatusResponse,
  TaskSnapshot,
  TaskStatus,
} from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

vi.mock("../../../shared/plugin/PluginSlot", () => ({ PluginSlot: () => null }));

const makeServer = (o: Partial<PerceptionLocalServerStatus> = {}): PerceptionLocalServerStatus => ({
  baseUrl: "http://127.0.0.1:8091/v1",
  detectedPythonPath: "runtime/python.exe",
  error: "",
  logs: [],
  managed: false,
  model: "Qwen/Qwen3-VL-2B-Instruct",
  pid: null,
  pythonPath: "runtime/python.exe",
  running: false,
  starting: false,
  state: "stopped",
  ...o,
});

const makeStatus = (): PerceptionStatusResponse => ({
  chatSessionActive: true,
  config: {
    baseUrl: "http://127.0.0.1:8091/v1",
    diffThreshold: 0.035,
    enabled: false,
    frameMaxSide: 512,
    intervalSec: 2,
    model: "Qwen/Qwen3-VL-2B-Instruct",
    proactiveCooldownSec: 25,
    proactiveEnabled: true,
    reflexCooldownSec: 4,
    reflexEnabled: true,
    salienceThreshold: 0.85,
  },
  ingestUrl: "http://127.0.0.1:8787/api/perception/ingest",
  localServer: makeServer(),
  runtime: null,
  setup: { downloadable: true, modelCached: true, pythonPath: "runtime/python.exe", status: "ready" },
});

const baseProps = {
  errorDetail: "",
  errorKind: null,
  health: null,
  localServer: null,
  onCancel: () => {},
  onPrepareAndStart: () => {},
  onProceedToShare: () => {},
  onRetry: () => {},
  open: true,
  phase: "checking" as const,
  setup: null,
  setupTask: null,
  status: null,
};

describe("ScreenSharePreflightDialog", () => {
  let originalMediaDevices: PropertyDescriptor | undefined;

  beforeEach(() => {
    originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getDisplayMedia: vi.fn() } });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
    else Reflect.deleteProperty(navigator, "mediaDevices");
  });

  it("renders installDependency label when model is cached and setup_error details", () => {
    const onPrepareAndStart = vi.fn();
    const { rerender } = render(
      <I18nProvider language="zh_CN">
        <ScreenSharePreflightDialog
          {...baseProps}
          onPrepareAndStart={onPrepareAndStart}
          phase="setup_needed"
          setup={{ downloadable: true, modelCached: true, packageName: "rapidocr", status: "missing_dependency" }}
        />
      </I18nProvider>,
    );

    expect(screen.getByText("缺少 rapidocr 等运行依赖")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "安装依赖" }));
    expect(onPrepareAndStart).toHaveBeenCalledTimes(1);

    rerender(
      <I18nProvider language="zh_CN">
        <ScreenSharePreflightDialog
          {...baseProps}
          errorDetail="Python runtime missing"
          errorKind="setup_error"
          phase="error"
        />
      </I18nProvider>,
    );
    expect(screen.getByText("Python runtime missing")).toBeVisible();

    rerender(
      <I18nProvider language="zh_CN">
        <ScreenSharePreflightDialog {...baseProps} errorDetail="" errorKind="unknown" phase="error" />
      </I18nProvider>,
    );
    expect(screen.getByText("检测实时反应服务失败")).toBeVisible();
  });

  it("renders download/verify task phases during installing and stays hidden when closed", () => {
    const makeTask = (phase: string, status: TaskStatus = "running"): TaskSnapshot => ({
      createdAt: 1,
      id: "t-model",
      kind: "model-download",
      logs: [],
      message: "working",
      phase,
      progress: 0.4,
      status,
      title: "download",
      updatedAt: 1,
    });

    const { rerender } = render(
      <I18nProvider language="zh_CN">
        <ScreenSharePreflightDialog {...baseProps} phase="installing" setupTask={makeTask("verify")} />
      </I18nProvider>,
    );
    expect(screen.getAllByText("正在校验感知模型…").length).toBeGreaterThan(0);

    rerender(
      <I18nProvider language="zh_CN">
        <ScreenSharePreflightDialog {...baseProps} phase="installing" setupTask={makeTask("download")} />
      </I18nProvider>,
    );
    expect(screen.getAllByText("正在下载感知视觉模型…").length).toBeGreaterThan(0);

    rerender(
      <I18nProvider language="zh_CN">
        <ScreenSharePreflightDialog {...baseProps} open={false} />
      </I18nProvider>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancels in-flight check when dialog closes", async () => {
    let resolveCheck!: (value: PerceptionStatusResponse) => void;
    const statusSpy = vi.spyOn(perceptionRepo, "getPerceptionStatus").mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveCheck = resolve;
        }),
    );
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer");

    function CancelHarness() {
      const [open, setOpen] = useState(false);
      const preflight = useScreenSharePreflight({
        onOpenChange: setOpen,
        onStartSharing: vi.fn(),
        open,
        screenShareStarting: false,
        screenSharing: false,
        sessionClosed: false,
      });
      return (
        <I18nProvider language="zh_CN">
          <button onClick={() => void preflight.openAndCheck()} type="button">
            触发共享屏幕
          </button>
          <ScreenSharePreflightDialog
            errorDetail={preflight.errorDetail}
            errorKind={preflight.errorKind}
            health={preflight.health}
            localServer={preflight.localServer}
            onCancel={preflight.close}
            onPrepareAndStart={() => void preflight.prepareAndStart()}
            onProceedToShare={preflight.proceedToShare}
            onRetry={() => void preflight.retry()}
            open={open}
            phase={preflight.phase}
            setup={preflight.setup}
            setupTask={preflight.setupTask}
            status={preflight.status}
          />
        </I18nProvider>
      );
    }

    render(<CancelHarness />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    expect(screen.getByRole("dialog")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    resolveCheck(makeStatus());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startSpy).not.toHaveBeenCalled();
    expect(statusSpy).toHaveBeenCalledTimes(1);
  });

  it("integrates with ChatStagePage and keeps local server running when stopping screen share", async () => {
    const track = { onended: null, readyState: "live", muted: false, stop: vi.fn() };
    const getDisplayMedia = vi
      .fn()
      .mockResolvedValue({ getAudioTracks: () => [], getTracks: () => [track], getVideoTracks: () => [track] });
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getDisplayMedia } });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(perceptionRepo, "ingestPerception").mockResolvedValue({ accepted: true, ok: true });
    vi.spyOn(perceptionRepo, "getPerceptionStatus").mockResolvedValueOnce(makeStatus());
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer").mockResolvedValue({
      localServer: makeServer({ managed: true, running: true, state: "running" }),
      ok: true,
    });
    const stopSpy = vi.spyOn(perceptionRepo, "stopPerceptionLocalServer");

    render(
      <ToastProvider>
        <MemoryRouter>
          <I18nProvider language="zh_CN">
            <ChatStagePage />
          </I18nProvider>
        </MemoryRouter>
      </ToastProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "共享屏幕" }));
    await waitFor(() => expect(startSpy).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: "选择共享窗口" }));
    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByRole("button", { name: "停止屏幕共享" }));
    expect(track.stop).toHaveBeenCalled();
    expect(stopSpy).not.toHaveBeenCalled();
  });
});
