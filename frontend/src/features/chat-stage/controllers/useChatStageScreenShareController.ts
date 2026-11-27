import { useCallback, useEffect, useState } from "react";

import type { MessageKey } from "../../../shared/i18n";
import type { ToastPayload } from "../../../shared/ui";
import type { ChatStageState } from "../chatState";
import { useScreenShareCapture } from "../hooks/useScreenShareCapture";
import { useScreenSharePreflight } from "../hooks/useScreenSharePreflight";

export interface UseChatStageScreenShareControllerOptions {
  characterAudioPlaying: boolean;
  perception: ChatStageState["perception"];
  perceptionCaptureRequestSeq?: number;
  sessionClosed: boolean;
  showToast: (options: ToastPayload) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
}

export function useChatStageScreenShareController({
  characterAudioPlaying,
  perception,
  perceptionCaptureRequestSeq,
  sessionClosed,
  showToast,
  t,
}: UseChatStageScreenShareControllerOptions) {
  const [screenSettingsOpen, setScreenSettingsOpen] = useState(false);
  const [screenSharePreflightOpen, setScreenSharePreflightOpen] = useState(false);

  const {
    changeOcrScope,
    ocrScope,
    playbackAudio,
    sharing: screenSharing,
    startSharing: startScreenShare,
    stream: screenShareStream,
    starting: screenShareStarting,
    stopSharing: stopScreenShare,
  } = useScreenShareCapture({
    captureRequestSeq: perceptionCaptureRequestSeq,
    captureIntervalSec: perception?.captureIntervalSec ?? 0.5,
    diffThreshold: perception?.diffThreshold ?? 0.035,
    frameMaxSide: perception?.frameMaxSide ?? 512,
    ocrIntervalSec: perception?.ocrIntervalSec ?? 1,
    ocrEnabled: perception?.ocrEnabled ?? false,
    proactiveEnabled: perception?.proactiveEnabled ?? true,
    playbackAudioSettings: perception?.screenPlaybackAudioSettings,
    characterAudioPlaying,
    onBlackScreen: () => {
      showToast({ kind: "info", title: t("chat.perception.blackFrame") });
    },
    onError: (error, unsupported) => {
      showToast({
        kind: "error",
        message: unsupported
          ? t("chat.perception.shareUnsupported")
          : error instanceof Error
            ? error.message
            : undefined,
        title: t("chat.perception.shareFailed"),
      });
    },
    onFrameError: () => {
      showToast({ kind: "error", title: t("chat.perception.frameUploadFailed") });
    },
    onStarted: () => {
      showToast({ kind: "info", title: t("chat.perception.shareStarted") });
    },
    onStopped: () => {
      showToast({ kind: "info", title: t("chat.perception.shareStopped") });
    },
    sessionClosed,
  });

  const screenSharePreflight = useScreenSharePreflight({
    open: screenSharePreflightOpen,
    onOpenChange: setScreenSharePreflightOpen,
    onStartSharing: startScreenShare,
    screenSharing,
    screenShareStarting,
    sessionClosed,
  });

  const openScreenSharePreflight = screenSharePreflight.openAndCheck;
  const handleToggleScreenShare = useCallback(() => {
    if (screenSharing) {
      stopScreenShare();
      return;
    }
    void openScreenSharePreflight();
  }, [openScreenSharePreflight, screenSharing, stopScreenShare]);

  useEffect(() => {
    if (!screenSharing) setScreenSettingsOpen(false);
  }, [screenSharing]);

  return {
    changeOcrScope,
    handleToggleScreenShare,
    ocrScope,
    playbackAudio,
    screenSettingsOpen,
    screenSharePreflight,
    screenSharePreflightOpen,
    screenShareStarting,
    screenShareStream,
    screenSharing,
    setScreenSettingsOpen,
    setScreenSharePreflightOpen,
  };
}
