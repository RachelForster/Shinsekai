/// <reference types="vitest/jsdom" />

import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as perceptionRepo from "../../../entities/perception/repository";
import { PerceptionSettingsSection } from "../../../features/api-settings/PerceptionSettingsSection";
import { DialogStageControls } from "../../../features/chat-stage/components/DialogStageControls";
import { ReactionBubble } from "../../../features/chat-stage/components/ReactionBubble";
import { ScreenShareSettingsDialog } from "../../../features/chat-stage/components/ScreenShareSettingsDialog";
import { createScreenPlaybackDetector } from "../../../features/chat-stage/hooks/screenPlaybackAudio";
import { useScreenShareCapture } from "../../../features/chat-stage/hooks/useScreenShareCapture";
import { emptyChatState } from "../../../features/chat-stage/state/initialState";
import { applyStageEvent } from "../../../features/chat-stage/state/events";
import { hydrateFromSnapshot } from "../../../features/chat-stage/state/snapshot";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { ChatSnapshot } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

vi.mock("../../../shared/plugin/PluginSlot", () => ({
  PluginSlot: () => null,
}));

describe("Perception chat-stage state & components", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("folds sprite.reaction and clears it when main RP dialogue or TTS arrives", () => {
    let state = applyStageEvent(
      emptyChatState,
      {
        characterName: "Nanami",
        durationMs: 3000,
        seq: 1,
        text: "小心左边！",
        ts: 1000,
        type: "sprite.reaction",
        v: 1,
      },
      500,
    );
    expect(state.spriteReaction).toEqual({
      characterName: "Nanami",
      deadline: 3500,
      durationMs: 3000,
      seq: 1,
      text: "小心左边！",
    });

    state = applyStageEvent(
      state,
      {
        color: "#ff88aa",
        fullHtml: "<p>正式回应台词</p>",
        isSystem: false,
        seq: 2,
        speaker: "Nanami",
        ts: 1200,
        type: "dialog.end",
        v: 1,
      },
      700,
    );
    expect(state.spriteReaction).toBeNull();
  });

  it("restores unexpired spriteReaction from snapshot without extending deadline", () => {
    const snapshot: ChatSnapshot = {
      dialogText: "Hello",
      eventSeq: 4,
      inputDraft: "",
      options: [],
      perception: {
        active: true,
        baseUrl: "http://127.0.0.1:8091/v1",
        diffThreshold: 0.035,
        enabled: true,
        frameMaxSide: 512,
        intervalSec: 2,
        lastError: "",
        model: "Qwen/Qwen3-VL-2B-Instruct",
        proactiveEnabled: true,
        reflexEnabled: true,
        salienceThreshold: 0.78,
        screenShareActive: true,
      },
      serverTimeMs: 10_000,
      sessionId: "sess-1",
      spriteReaction: {
        characterName: "Nanami",
        durationMs: 3600,
        expiresAt: 12_500,
        seq: 4,
        text: "咦？",
      },
      sprites: [],
      status: "idle",
    };

    const hydrated = hydrateFromSnapshot(emptyChatState, snapshot, 200);
    expect(hydrated.perception?.screenShareActive).toBe(true);
    expect(hydrated.spriteReaction).toEqual({
      characterName: "Nanami",
      deadline: 2700,
      durationMs: 3600,
      seq: 4,
      text: "咦？",
    });
  });

  it("renders ReactionBubble and auto-expires after deadline", () => {
    const now = performance.now();
    render(
      <ReactionBubble
        reaction={{
          characterName: "Nanami",
          deadline: now + 1500,
          durationMs: 1500,
          seq: 7,
          text: "好险！",
        }}
        sprites={[
          {
            avatarType: "static",
            characterName: "Nanami",
            id: "Nanami",
            label: "Nanami",
            modelUrl: "",
            path: "/sprite.png",
            slot: 1,
          },
        ]}
      />,
    );

    expect(screen.getByRole("status").textContent).toContain("好险！");

    act(() => {
      vi.advanceTimersByTime(1600);
    });

    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders Share Screen button in DialogStageControls and invokes toggle callback", () => {
    const onToggleScreenShare = vi.fn();
    render(
      <I18nProvider language="zh_CN">
        <ToastProvider>
          <DialogStageControls
            asrEnabled={false}
            auto={false}
            bgmVolume={50}
            closeLabel="关闭"
            configOpen={false}
            effectVolume={50}
            hidden={false}
            hideCloseButton={false}
            locked={false}
            longPressTalk={false}
            onAutoChange={() => {}}
            onBgmVolumeChange={() => {}}
            onCancelBatch={() => {}}
            onCloseSurface={() => {}}
            onCommand={() => {}}
            onConfigOpenChange={() => {}}
            onEffectVolumeChange={() => {}}
            onFlushBatch={() => {}}
            onLockedChange={() => {}}
            onLongPressTalkChange={() => {}}
            onOpenBranches={() => {}}
            onOpenHistory={() => {}}
            onOpenPluginPage={() => {}}
            onToggleScreenShare={onToggleScreenShare}
            onTurnOptionsChange={() => {}}
            screenSharing={false}
            showAsrControl={false}
            showBranches={false}
            turnOptions={{ batchEnabled: false, batchIdleSeconds: 5, interruptEnabled: true }}
            turnState={{
              enabled: false,
              pendingCount: 0,
              pendingMessages: [],
              remainingSeconds: null,
              scheduled: false,
              typing: false,
            }}
          />
        </ToastProvider>
      </I18nProvider>,
    );

    const button = screen.getByRole("button", { name: /共享屏幕/ });
    fireEvent.click(button);
    expect(onToggleScreenShare).toHaveBeenCalledTimes(1);
  });

  it("switches OCR presets and draws a normalized selection on the shared preview", () => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1600);
    vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(800);
    const onScopeChange = vi.fn();
    try {
      const { container, unmount } = render(
        <I18nProvider language="zh_CN">
          <ScreenShareSettingsDialog
            ocrEnabled
            onClose={() => {}}
            onScopeChange={onScopeChange}
            scope={{ mode: "bottom" }}
            stream={{} as MediaStream}
          />
        </I18nProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "全屏文字" }));
      expect(onScopeChange).toHaveBeenLastCalledWith({ mode: "full" });
      fireEvent.loadedMetadata(container.querySelector("video")!);
      const preview = screen.getByRole("group", { name: "共享画面预览" });
      vi.spyOn(preview, "getBoundingClientRect").mockReturnValue(new DOMRect(100, 50, 800, 400));
      for (const [type, clientX, clientY] of [
        ["pointerdown", 700, 350],
        ["pointerup", 300, 150],
      ] as const) {
        const event = new MouseEvent(type, { bubbles: true, button: 0, clientX, clientY });
        Object.defineProperty(event, "pointerId", { value: 1 });
        fireEvent(preview, event);
      }
      expect(onScopeChange).toHaveBeenLastCalledWith({
        mode: "region",
        region: { x: 0.25, y: 0.25, width: 0.5, height: 0.5 },
      });
      unmount();
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("detects a sustained volume drop and waits for silence and a still image before inferring a pause", () => {
    const detect = createScreenPlaybackDetector();
    expect(detect(null, 0, 0)).toBe("unavailable");
    expect(detect(0.1, 120, 0)).toBe("playing");
    expect(detect(0.09, 480, 0)).toBe("playing");
    expect(detect(0.02, 600, 0)).toBe("playing");
    expect(detect(0.02, 1200, 1100)).toBe("quiet");
    expect(detect(0, 3000, 1000)).toBe("quiet");
    expect(detect(0, 5400, 5300)).toBe("quiet");
    expect(detect(0, 6600, 5300)).toBe("stopped");
    expect(detect(0.08, 6720, 6600)).toBe("playing");
  });

  it("reports playback audio state even when no screen frames are being uploaded", async () => {
    const track = { onended: null, readyState: "live", muted: false, stop: vi.fn() };
    const getDisplayMedia = vi.fn().mockResolvedValue({
      getAudioTracks: () => [track],
      getTracks: () => [track],
      getVideoTracks: () => [track],
    });
    const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getDisplayMedia } });
    let level = 0.1;
    const close = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal(
      "AudioContext",
      class {
        state = "running";
        close = close;
        createMediaStreamSource = () => ({ connect: vi.fn(), disconnect: vi.fn() });
        createAnalyser = () => ({ getFloatTimeDomainData: (samples: Float32Array) => samples.fill(level) });
      },
    );
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    const ingest = vi.spyOn(perceptionRepo, "ingestPerception").mockResolvedValue({ ok: true, accepted: true });
    const clock = vi.spyOn(performance, "now").mockReturnValue(0);
    const { result, unmount } = renderHook(() => useScreenShareCapture({}));
    async function sample(at: number) {
      clock.mockReturnValue(at);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(120);
      });
    }
    try {
      await act(async () => {
        result.current.toggleSharing();
      });
      expect(getDisplayMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: true }));
      await sample(120);
      expect(ingest).toHaveBeenLastCalledWith(expect.objectContaining({ screenPlaybackAudio: "playing" }));
      await sample(480);
      level = 0;
      await sample(600);
      await sample(1200);
      expect(ingest).toHaveBeenLastCalledWith(expect.objectContaining({ screenPlaybackAudio: "quiet" }));
      await sample(2880);
      expect(ingest).toHaveBeenLastCalledWith(expect.objectContaining({ screenPlaybackAudio: "stopped" }));
      expect(ingest.mock.calls.every(([input]) => !input.imageBase64)).toBe(true);
      await act(async () => {
        result.current.toggleSharing();
      });
      expect(close).toHaveBeenCalledTimes(1);
      expect(ingest).toHaveBeenLastCalledWith({ screenShareActive: false, source: "screen_share" });
    } finally {
      unmount();
      if (originalMediaDevices) {
        Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
      } else {
        Reflect.deleteProperty(navigator, "mediaDevices");
      }
      vi.unstubAllGlobals();
      vi.restoreAllMocks();
    }
  });

  it("skips black frames, retries a rejected frame, and refreshes a still screen", async () => {
    const track = { onended: null, readyState: "live", stop: vi.fn() };
    const getDisplayMedia = vi.fn().mockResolvedValue({
      getAudioTracks: () => [],
      getTracks: () => [track],
      getVideoTracks: () => [track],
    });
    const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getDisplayMedia },
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(2);
    vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1920);
    vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1080);
    const pixels = new Uint8ClampedArray(64 * 36 * 4);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
      getImageData: () => ({ data: pixels }),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,YQ==");
    const clock = vi.spyOn(performance, "now").mockReturnValue(0);
    const ingest = vi
      .spyOn(perceptionRepo, "ingestPerception")
      .mockResolvedValueOnce({ accepted: false, ok: false, reason: "no_active_chat_session" })
      .mockResolvedValue({ accepted: true, ok: true });
    const onFrameError = vi.fn();
    const onBlackScreen = vi.fn();
    const onStarted = vi.fn();
    const { result, rerender, unmount } = renderHook(
      (ocrEnabled) =>
        useScreenShareCapture({
          captureIntervalSec: 1,
          ocrEnabled,
          ocrIntervalSec: 0.5,
          onBlackScreen,
          onFrameError,
          onStarted,
        }),
      { initialProps: false },
    );

    try {
      await act(async () => {
        await result.current.startSharing();
      });
      expect(ingest).not.toHaveBeenCalled();
      expect(onBlackScreen).not.toHaveBeenCalled();

      clock.mockReturnValue(8_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(8_000);
      });
      expect(ingest).not.toHaveBeenCalled();
      expect(onBlackScreen).toHaveBeenCalledTimes(1);

      pixels.fill(128);
      clock.mockReturnValue(9_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(ingest).toHaveBeenCalledWith(expect.objectContaining({ imageBase64: "YQ==", screenShareActive: true }));
      expect(onFrameError).toHaveBeenCalledTimes(1);
      expect(onStarted).not.toHaveBeenCalled();

      clock.mockReturnValue(10_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(ingest).toHaveBeenCalledTimes(2);
      expect(onStarted).toHaveBeenCalledTimes(1);

      clock.mockReturnValue(11_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(ingest).toHaveBeenCalledTimes(2);

      clock.mockReturnValue(22_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(ingest).toHaveBeenCalledTimes(3);

      for (let row = 0; row < 12; row += 1) {
        const start = row * 64 * 4;
        pixels.fill(64, start, start + 16 * 4);
      }
      clock.mockReturnValue(23_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(ingest).toHaveBeenCalledTimes(4);

      rerender(true);
      clock.mockReturnValue(23_500);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
      expect(ingest).toHaveBeenCalledTimes(5);
      expect(ingest).toHaveBeenLastCalledWith(expect.objectContaining({ ocrOnly: true, width: 1280, height: 720 }));

      clock.mockReturnValue(24_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
      expect(ingest).toHaveBeenLastCalledWith(expect.objectContaining({ ocrOnly: true }));

      for (let row = 31; row < 36; row += 1) {
        const start = (row * 64 + 32) * 4;
        pixels.fill(64, start, start + 8 * 4);
      }
      clock.mockReturnValue(25_000);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      expect(ingest.mock.calls.filter(([input]) => !input.ocrOnly)).toHaveLength(5);
      expect(onStarted).toHaveBeenCalledTimes(1);

      const region = { x: 0.1, y: 0.7, width: 0.8, height: 0.2 };
      await act(async () => result.current.changeOcrScope({ mode: "region", region }));
      expect(ingest).toHaveBeenLastCalledWith(
        expect.objectContaining({
          ocrOnly: true,
          ocrScope: { mode: "region", region },
          width: 1280,
          height: 720,
        }),
      );
    } finally {
      await act(async () => {
        unmount();
      });
      if (originalMediaDevices) {
        Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
      } else {
        Reflect.deleteProperty(navigator, "mediaDevices");
      }
      vi.restoreAllMocks();
    }
  });

  it("supports one-click start and stop of local perception server in PerceptionSettingsSection", async () => {
    vi.useRealTimers();
    const statusSpy = vi
      .spyOn(perceptionRepo, "getPerceptionStatus")
      .mockResolvedValueOnce({
        chatSessionActive: false,
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
          salienceThreshold: 0.78,
        },
        ingestUrl: "http://127.0.0.1:8787/api/perception/ingest",
        localServer: {
          baseUrl: "http://127.0.0.1:8091/v1",
          detectedPythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
          error: "",
          logs: [],
          managed: false,
          model: "Qwen/Qwen3-VL-2B-Instruct",
          pid: null,
          pythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
          running: false,
          starting: false,
          state: "stopped",
        },
        runtime: null,
      })
      .mockResolvedValue({
        chatSessionActive: false,
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
          salienceThreshold: 0.78,
        },
        health: {
          baseUrl: "http://127.0.0.1:8091/v1",
          configuredModel: "Qwen/Qwen3-VL-2B-Instruct",
          modelPresent: true,
          models: ["Qwen/Qwen3-VL-2B-Instruct"],
          ok: true,
        },
        ingestUrl: "http://127.0.0.1:8787/api/perception/ingest",
        localServer: {
          baseUrl: "http://127.0.0.1:8091/v1",
          detectedPythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
          error: "",
          logs: ["[perception-server] Ready in 2.2s | VRAM: 4135.2 MB"],
          managed: true,
          model: "Qwen/Qwen3-VL-2B-Instruct",
          pid: 4242,
          pythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
          running: true,
          starting: false,
          state: "running",
        },
        runtime: null,
      });
    const startSpy = vi.spyOn(perceptionRepo, "startPerceptionLocalServer").mockResolvedValue({
      localServer: {
        baseUrl: "http://127.0.0.1:8091/v1",
        detectedPythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
        error: "",
        logs: ["[perception-server] Ready in 2.2s | VRAM: 4135.2 MB"],
        managed: true,
        model: "Qwen/Qwen3-VL-2B-Instruct",
        pid: 4242,
        pythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
        running: true,
        starting: false,
        state: "running",
      },
      ok: true,
    });
    const stopSpy = vi.spyOn(perceptionRepo, "stopPerceptionLocalServer").mockResolvedValue({
      localServer: {
        baseUrl: "http://127.0.0.1:8091/v1",
        detectedPythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
        error: "",
        logs: ["[launcher] Local perception server stopped."],
        managed: false,
        model: "Qwen/Qwen3-VL-2B-Instruct",
        pid: null,
        pythonPath: "C:\\conda\\envs\\eaiv\\python.exe",
        running: false,
        starting: false,
        state: "stopped",
      },
      ok: true,
    });
    const imageHealth = {
      baseUrl: "http://127.0.0.1:8091/v1",
      configuredModel: "Qwen/Qwen3-VL-2B-Instruct",
      imageTest: { ok: true },
      modelPresent: true,
      models: ["Qwen/Qwen3-VL-2B-Instruct"],
      ok: true,
    };
    const imageTestSpy = vi
      .spyOn(perceptionRepo, "testPerceptionImage")
      .mockResolvedValueOnce({ ...imageHealth, imageTest: { ok: false, error: "Invalid image response" } })
      .mockResolvedValue(imageHealth);
    const updateDraft = vi.fn();

    try {
      const { container } = render(
        <I18nProvider language="zh_CN">
          <ToastProvider>
            <PerceptionSettingsSection draft={sampleConfig.api_config} onChange={updateDraft} />
          </ToastProvider>
        </I18nProvider>,
      );

      const outerDetails = container.querySelector("details.perception-settings") as HTMLDetailsElement;
      const advancedDetails = container.querySelector("details.perception-settings__advanced") as HTMLDetailsElement;
      expect(outerDetails).not.toBeNull();
      expect(advancedDetails).not.toBeNull();
      expect(outerDetails.open).toBe(false);
      expect(advancedDetails.open).toBe(false);

      fireEvent.click(screen.getByText("实时感知与游戏反应").closest("summary")!);
      expect(outerDetails.open).toBe(true);
      expect(advancedDetails.open).toBe(false);

      expect(screen.getByRole("checkbox", { name: "主动发言" })).toBeVisible();
      expect(screen.getByLabelText("视觉模型")).not.toBeVisible();
      const startBtn = await screen.findByRole("button", { name: "启动本地服务" });
      fireEvent.click(startBtn);

      await waitFor(() => {
        expect(startSpy).toHaveBeenCalledTimes(1);
      });
      expect(await screen.findByText("已连接")).toBeVisible();

      fireEvent.click(screen.getByRole("button", { name: "测试视觉" }));
      expect(await screen.findByText("图像测试失败：Invalid image response")).toBeVisible();
      expect(screen.queryByText("已连接")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "测试视觉" }));
      expect(await screen.findByText("视觉测试通过")).toBeVisible();
      expect(imageTestSpy).toHaveBeenCalledTimes(2);

      const stopBtn = await screen.findByRole("button", { name: "停止本地服务" });
      fireEvent.click(stopBtn);
      await waitFor(() => {
        expect(stopSpy).toHaveBeenCalledTimes(1);
      });
      expect(await screen.findByRole("button", { name: "启动本地服务" })).toBeVisible();

      fireEvent.click(screen.getByText("高级设置").closest("summary")!);
      expect(advancedDetails.open).toBe(true);
      expect(screen.getByLabelText("视觉模型")).toBeVisible();
      fireEvent.click(screen.getByRole("checkbox", { name: "本地 OCR" }));
      expect(updateDraft).toHaveBeenLastCalledWith(expect.objectContaining({ perception_ocr_enabled: true }));
    } finally {
      statusSpy.mockRestore();
      startSpy.mockRestore();
      stopSpy.mockRestore();
      imageTestSpy.mockRestore();
    }
  });
});
