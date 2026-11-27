/// <reference types="vitest/jsdom" />

import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as chatRepo from "../../../entities/chat/repository";
import * as modelAssetsRepo from "../../../entities/model-assets/repository";
import * as perceptionRepo from "../../../entities/perception/repository";
import { ScreenSharePreflightDialog } from "../../../features/chat-stage/components/ScreenSharePreflightDialog";
import {
  isLocalPerceptionBaseUrl,
  useScreenSharePreflight,
} from "../../../features/chat-stage/hooks/useScreenSharePreflight";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type {
  PerceptionHealthProbe,
  PerceptionLocalServerStatus,
  PerceptionSetupStatus,
  PerceptionStatusResponse,
} from "../../../shared/platform/types";

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

const makeSetup = (o: Partial<PerceptionSetupStatus> = {}): PerceptionSetupStatus => ({
  downloadable: true,
  modelCached: true,
  pythonPath: "runtime/python.exe",
  status: "ready",
  ...o,
});

const makeHealth = (o: Partial<PerceptionHealthProbe> = {}): PerceptionHealthProbe => ({
  baseUrl: "http://127.0.0.1:8091/v1",
  configuredModel: "Qwen/Qwen3-VL-2B-Instruct",
  modelPresent: true,
  models: ["Qwen/Qwen3-VL-2B-Instruct"],
  ok: true,
  ...o,
});

const makeStatus = (o: Partial<PerceptionStatusResponse> = {}): PerceptionStatusResponse => ({
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
  setup: makeSetup(),
  ...o,
});

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function PreflightHarness({ onStartSharing }: { onStartSharing: () => Promise<void> | void }) {
  const [open, setOpen] = useState(false);
  const preflight = useScreenSharePreflight({
    onOpenChange: setOpen,
    onStartSharing,
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
        installingPackage={preflight.installingPackage}
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

describe("ScreenSharePreflight", () => {
  let originalMediaDevices: PropertyDescriptor | undefined;

  beforeEach(() => {
    originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getDisplayMedia: vi.fn() } });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
    else Reflect.deleteProperty(navigator, "mediaDevices");
  });

  it("identifies local vs remote perception base URLs", () => {
    expect(isLocalPerceptionBaseUrl(undefined)).toBe(true);
    expect(isLocalPerceptionBaseUrl("")).toBe(true);
    expect(isLocalPerceptionBaseUrl("http://127.0.0.1:8091/v1")).toBe(true);
    expect(isLocalPerceptionBaseUrl("http://localhost:8091/v1")).toBe(true);
    expect(isLocalPerceptionBaseUrl("http://0.0.0.0:8091/v1")).toBe(true);
    expect(isLocalPerceptionBaseUrl("http://[::1]:8091/v1")).toBe(true);
    expect(isLocalPerceptionBaseUrl("https://127.0.0.1:8091/v1")).toBe(false);
    expect(isLocalPerceptionBaseUrl("http://192.168.1.50:8091/v1")).toBe(false);
    expect(isLocalPerceptionBaseUrl("https://vision.example.com/v1")).toBe(false);
    expect(isLocalPerceptionBaseUrl("not-a-url")).toBe(false);
  });

  it("auto-closes and immediately starts sharing when service is already ready and fast", async () => {
    const onStartSharing = vi.fn();
    vi.spyOn(perceptionRepo, "getPerceptionStatus").mockResolvedValueOnce(
      makeStatus({ health: makeHealth(), localServer: makeServer({ managed: true, running: true, state: "running" }) }),
    );
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer");

    render(<PreflightHarness onStartSharing={onStartSharing} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));

    await waitFor(() => expect(onStartSharing).toHaveBeenCalledTimes(1));
    expect(startSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("lands on ready prompt when initial service check exceeds gesture window", async () => {
    vi.useFakeTimers();
    const onStartSharing = vi.fn();
    let resolveCheck!: (value: PerceptionStatusResponse) => void;
    vi.spyOn(perceptionRepo, "getPerceptionStatus").mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveCheck = resolve;
        }),
    );

    render(<PreflightHarness onStartSharing={onStartSharing} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    expect(screen.getByText("正在检测实时反应服务状态…")).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4500);
      resolveCheck(makeStatus({ health: makeHealth() }));
      await Promise.resolve();
    });

    expect(screen.getByText("实时反应服务已就绪")).toBeVisible();
    expect(onStartSharing).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "选择共享窗口" }));
    expect(onStartSharing).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("auto-starts stopped local server, polls until ready, and supports early sharing", async () => {
    vi.useFakeTimers();
    const onStartSharing = vi.fn();
    const statusSpy = vi
      .spyOn(perceptionRepo, "getPerceptionStatus")
      .mockResolvedValueOnce(makeStatus({ health: makeHealth({ modelPresent: false, models: [], ok: false }) }))
      .mockResolvedValueOnce(
        makeStatus({ localServer: makeServer({ logs: ["Loading weights..."], starting: true, state: "starting" }) }),
      )
      .mockResolvedValueOnce(
        makeStatus({
          localServer: makeServer({ logs: ["Ready in 1.4s"], managed: true, running: true, state: "running" }),
        }),
      );
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer").mockResolvedValue({
      localServer: makeServer({ logs: ["Starting server..."], starting: true, state: "starting" }),
      ok: true,
    });

    render(<PreflightHarness onStartSharing={onStartSharing} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    await flushMicrotasks();

    expect(startSpy).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("加载模型中…").length).toBeGreaterThan(0);
    expect(screen.getByText("Starting server...")).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(screen.getByText("Loading weights...")).toBeVisible();
    expect(screen.getByRole("button", { name: "先选择共享窗口" })).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(screen.getByText("实时反应服务已就绪")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "选择共享窗口" }));
    expect(onStartSharing).toHaveBeenCalledTimes(1);
    expect(statusSpy).toHaveBeenCalledTimes(3);

    startSpy.mockClear();
    statusSpy
      .mockResolvedValueOnce(makeStatus({ health: makeHealth({ modelPresent: false, models: [], ok: false }) }))
      .mockResolvedValue(makeStatus({ localServer: makeServer({ starting: true, state: "starting" }) }));
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    await flushMicrotasks();
    fireEvent.click(screen.getByRole("button", { name: "先选择共享窗口" }));
    expect(onStartSharing).toHaveBeenCalledTimes(2);
  });

  it("resumes polling when local server is already starting and fails after 3 poll errors", async () => {
    vi.useFakeTimers();
    const statusSpy = vi
      .spyOn(perceptionRepo, "getPerceptionStatus")
      .mockResolvedValueOnce(
        makeStatus({ localServer: makeServer({ logs: ["Warming up"], starting: true, state: "starting" }) }),
      )
      .mockResolvedValueOnce(
        makeStatus({ localServer: makeServer({ managed: true, running: true, state: "running" }) }),
      );
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer");

    render(<PreflightHarness onStartSharing={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    await flushMicrotasks();
    expect(startSpy).not.toHaveBeenCalled();
    expect(screen.getByText("Warming up")).toBeVisible();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(screen.getByText("实时反应服务已就绪")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    statusSpy
      .mockResolvedValueOnce(makeStatus({ localServer: makeServer({ starting: true, state: "starting" }) }))
      .mockRejectedValue(new Error("poll network error"));
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    await flushMicrotasks();
    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(900);
      });
    }
    expect(screen.getByText("poll network error")).toBeVisible();
  });

  it("handles server startup failure and 120s timeout error with retry and cancel", async () => {
    vi.useFakeTimers();
    const onStartSharing = vi.fn();
    const statusSpy = vi
      .spyOn(perceptionRepo, "getPerceptionStatus")
      .mockResolvedValueOnce(makeStatus())
      .mockResolvedValueOnce(
        makeStatus({
          localServer: makeServer({
            error: "等待本地模型加载超时（120s）",
            logs: ["CUDA OOM"],
            starting: true,
            state: "starting",
          }),
        }),
      )
      .mockResolvedValueOnce(makeStatus());
    vi.spyOn(perceptionRepo, "startPerceptionLocalServer")
      .mockResolvedValueOnce({ localServer: makeServer({ starting: true, state: "starting" }), ok: true })
      .mockResolvedValueOnce({ localServer: makeServer({ running: true, state: "running" }), ok: true });

    render(<PreflightHarness onStartSharing={onStartSharing} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    await flushMicrotasks();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });

    expect(screen.getByText("启动失败：等待本地模型加载超时（120s）")).toBeVisible();
    expect(screen.getByText("CUDA OOM")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "重新检测" }));
    await flushMicrotasks();
    expect(screen.getByText("实时反应服务已就绪")).toBeVisible();
    expect(statusSpy).toHaveBeenCalledTimes(3);

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onStartSharing).not.toHaveBeenCalled();
  });

  it("installs missing dependency, downloads default or custom model, and auto-starts server", async () => {
    const missingDep = makeSetup({
      modelCached: false,
      moduleName: "perception",
      packageName: "torch>=2.5",
      pythonPath: "C:\\Py\\python.exe",
      status: "missing_dependency",
    });
    const statusSpy = vi
      .spyOn(perceptionRepo, "getPerceptionStatus")
      .mockResolvedValueOnce(makeStatus({ setup: missingDep }))
      .mockResolvedValueOnce(makeStatus({ setup: missingDep }))
      .mockResolvedValueOnce(makeStatus({ setup: makeSetup({ modelCached: false, status: "not_started" }) }))
      .mockResolvedValueOnce(makeStatus({ setup: makeSetup() }));
    const installSpy = vi
      .spyOn(chatRepo, "installMissingRuntimeDependency")
      .mockImplementation(async (_input, opts) => {
        opts?.onTaskUpdate?.({
          createdAt: 1,
          id: "t1",
          kind: "runtime-dependency-install",
          logs: [],
          message: "pip",
          phase: "pip",
          progress: 0.5,
          status: "running",
          title: "install",
          updatedAt: 1,
        });
        return { message: "ok", moduleName: "perception", packageName: "torch", pipCode: 0, pipOutput: "" };
      });
    const downloadSpy = vi.spyOn(modelAssetsRepo, "downloadModelAsset").mockResolvedValue({
      assetId: "perception.vlm",
      cached: true,
      downloadable: true,
      downloaded: true,
      repoId: "Qwen/Qwen3-VL-2B-Instruct",
      source: "huggingface",
      title: "VLM",
      variant: "Qwen/Qwen3-VL-2B-Instruct",
    });
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer").mockResolvedValue({
      localServer: makeServer({ managed: true, running: true, state: "running" }),
      ok: true,
    });

    render(<PreflightHarness onStartSharing={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    fireEvent.click(await screen.findByRole("button", { name: "下载依赖与模型" }));

    await waitFor(() =>
      expect(installSpy).toHaveBeenCalledWith(
        { moduleName: "perception", pythonPath: "C:\\Py\\python.exe" },
        expect.any(Object),
      ),
    );
    await waitFor(() => expect(downloadSpy).toHaveBeenCalledWith({ assetId: "perception.vlm" }, expect.any(Object)));
    await waitFor(() => expect(startSpy).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("实时反应服务已就绪")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    downloadSpy.mockClear();
    const customConfig = { ...makeStatus().config, model: "org/custom-vlm" };
    statusSpy
      .mockResolvedValueOnce(
        makeStatus({ config: customConfig, setup: makeSetup({ modelCached: false, status: "not_started" }) }),
      )
      .mockResolvedValueOnce(
        makeStatus({ config: customConfig, setup: makeSetup({ modelCached: false, status: "not_started" }) }),
      )
      .mockResolvedValueOnce(makeStatus({ config: customConfig, setup: makeSetup() }));

    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    fireEvent.click(await screen.findByRole("button", { name: "下载模型" }));
    await waitFor(() =>
      expect(downloadSpy).toHaveBeenCalledWith({ assetId: "perception.vlm", configured: true }, expect.any(Object)),
    );
  });

  it("shows error without downloading or starting when non-downloadable GGUF files are missing", async () => {
    vi.spyOn(perceptionRepo, "getPerceptionStatus").mockResolvedValueOnce(
      makeStatus({
        setup: makeSetup({
          downloadable: false,
          message: "Q4 感知服务缺少 llama-server.exe",
          modelCached: false,
          status: "not_started",
        }),
      }),
    );
    const downloadSpy = vi.spyOn(modelAssetsRepo, "downloadModelAsset");
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer");
    const onStartSharing = vi.fn();

    render(<PreflightHarness onStartSharing={onStartSharing} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));

    expect(await screen.findByText("Q4 感知服务缺少 llama-server.exe")).toBeVisible();
    expect(downloadSpy).not.toHaveBeenCalled();
    expect(startSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "仅共享屏幕" }));
    expect(onStartSharing).toHaveBeenCalledTimes(1);
  });

  it("reports unreachable, remote mismatch, and unmanaged local mismatch without starting local server", async () => {
    vi.spyOn(perceptionRepo, "getPerceptionStatus")
      .mockResolvedValueOnce(
        makeStatus({
          config: { ...makeStatus().config, baseUrl: "http://192.168.1.20:8091/v1" },
          health: makeHealth({
            baseUrl: "http://192.168.1.20:8091/v1",
            error: "connection refused",
            models: [],
            ok: false,
          }),
        }),
      )
      .mockResolvedValueOnce(
        makeStatus({
          config: { ...makeStatus().config, baseUrl: "https://remote.example.com/v1" },
          health: makeHealth({
            baseUrl: "https://remote.example.com/v1",
            modelPresent: false,
            models: ["other-model"],
            ok: true,
          }),
        }),
      )
      .mockResolvedValueOnce(
        makeStatus({
          health: makeHealth({ modelPresent: false, models: ["other-local"], ok: true }),
          localServer: makeServer({ managed: false, state: "stopped" }),
        }),
      );
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer");

    render(<PreflightHarness onStartSharing={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));
    expect(await screen.findByText("连接失败：connection refused")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "重新检测" }));
    expect(await screen.findByText("未找到配置的模型（可用：other-model）")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "重新检测" }));
    expect(await screen.findByText("未找到配置的模型（可用：other-local）")).toBeVisible();
    expect(startSpy).not.toHaveBeenCalled();
  });

  it("delegates directly when getDisplayMedia is unsupported without calling backend", () => {
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
    const statusSpy = vi.spyOn(perceptionRepo, "getPerceptionStatus");
    const onStartSharing = vi.fn();

    render(<PreflightHarness onStartSharing={onStartSharing} />);
    fireEvent.click(screen.getByRole("button", { name: "触发共享屏幕" }));

    expect(onStartSharing).toHaveBeenCalledTimes(1);
    expect(statusSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
