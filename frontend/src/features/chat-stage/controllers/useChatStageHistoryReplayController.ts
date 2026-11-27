import { useCallback, useEffect, useRef, useState, type Dispatch } from "react";

import { getChatHistoryVoice, getChatReplay } from "../../../entities/chat/repository";
import type { MessageKey } from "../../../shared/i18n";
import type { ChatCommand } from "../../../shared/platform/types";
import type { ToastPayload } from "../../../shared/ui";
import type { ChatSoundPlayerHandle } from "../audio/ChatSoundPlayer";
import type { ChatStageAction, ChatStageState, ChatStageViewModel } from "../chatState";
import { stageAssetUrl } from "../chatStageUtils";
import {
  saveCgAsset,
  saveHistoryExport,
  type HistoryExportFormat,
  type HistoryExportResult,
} from "../replay/historyExport";
import type { ActiveReplay } from "../replay/ReplayControls";
import { useReplayCapture } from "../replay/useReplayCapture";

export interface UseChatStageHistoryReplayControllerOptions {
  dispatch: Dispatch<ChatStageAction>;
  refreshHistory: () => Promise<void>;
  sendCommand: (command: ChatCommand) => Promise<void>;
  setAuto: (auto: boolean) => void;
  showToast: (options: ToastPayload) => void;
  state: ChatStageState;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
  viewModel: ChatStageViewModel;
}

export function useChatStageHistoryReplayController({
  dispatch,
  refreshHistory,
  sendCommand,
  setAuto,
  showToast,
  state,
  t,
  viewModel,
}: UseChatStageHistoryReplayControllerOptions) {
  const [confirmRevertUserIndex, setConfirmRevertUserIndex] = useState<number | null>(null);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [activeReplay, setActiveReplay] = useState<ActiveReplay | null>(null);
  const observedReplayIdRef = useRef<string>();
  const historyReplayRef = useRef<{ stop: () => void } | null>(null);
  const soundPlayerRef = useRef<ChatSoundPlayerHandle>(null);
  const historyReplayGenerationRef = useRef(0);
  const [savingCg, setSavingCg] = useState(false);
  const [historyExport, setHistoryExport] = useState<HistoryExportResult>();

  const exportHistory = useCallback(async (blob: Blob, format: HistoryExportFormat) => {
    setHistoryExport(await saveHistoryExport(blob, format));
  }, []);

  const historyPreviewUrl = historyExport?.previewUrl;
  useEffect(
    () => () => {
      if (historyPreviewUrl) URL.revokeObjectURL(historyPreviewUrl);
    },
    [historyPreviewUrl],
  );

  const capturingReplay = useReplayCapture(
    activeReplay?.capture,
    Boolean(state.replay && state.replay.id === activeReplay?.snapshot.id && state.replay.ended),
    exportHistory,
  );

  const stopHistoryReplay = useCallback(() => {
    historyReplayGenerationRef.current += 1;
    historyReplayRef.current?.stop();
    historyReplayRef.current = null;
  }, []);

  useEffect(() => () => stopHistoryReplay(), [stopHistoryReplay]);

  const replayHistoryVoice = useCallback(
    async (voiceId: string) => {
      stopHistoryReplay();
      const generation = historyReplayGenerationRef.current;
      try {
        const urls = await getChatHistoryVoice(voiceId);
        if (!urls.length) throw new Error("voice has no segments");
        for (const url of urls) {
          if (generation !== historyReplayGenerationRef.current) return;
          await new Promise<void>((resolve, reject) => {
            const audio = new Audio(url);
            let finished = false;
            const finish = (error?: unknown) => {
              if (finished) return;
              finished = true;
              audio.onended = null;
              audio.onerror = null;
              historyReplayRef.current = null;
              if (error) reject(error);
              else resolve();
            };
            audio.onended = () => finish();
            audio.onerror = () => finish(new Error("voice playback failed"));
            historyReplayRef.current = {
              stop: () => {
                audio.pause();
                finish();
              },
            };
            void audio.play().catch(finish);
          });
        }
      } catch {
        if (generation === historyReplayGenerationRef.current) {
          showToast({ kind: "error", title: t("chat.history.voiceExpired") });
        }
      }
    },
    [showToast, stopHistoryReplay, t],
  );

  const exitCg = useCallback(() => {
    dispatch({ type: "dismissCg" });
    if (!state.sessionClosedReason && !activeReplay && !state.replay) {
      void sendCommand({ type: "dismiss-cg" });
    }
  }, [activeReplay, dispatch, sendCommand, state.replay, state.sessionClosedReason]);

  const saveCg = useCallback(async () => {
    const cgUrl = stageAssetUrl(viewModel.cgPath);
    if (!cgUrl || savingCg) {
      return;
    }
    setSavingCg(true);
    try {
      const saved = await saveCgAsset(cgUrl);
      showToast({
        kind: "success",
        message: saved.path ?? saved.name,
        title: t("chat.cg.saved"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : undefined,
        title: t("chat.cg.saveFailed"),
      });
    } finally {
      setSavingCg(false);
    }
  }, [savingCg, showToast, t, viewModel.cgPath]);

  const openHistoryDialog = () => {
    setHistoryDialogOpen(true);
    void refreshHistory();
  };

  const closeHistoryDialog = useCallback(() => {
    stopHistoryReplay();
    setHistoryDialogOpen(false);
  }, [stopHistoryReplay]);

  const startReplay = useCallback(
    (replay: ActiveReplay) => {
      stopHistoryReplay();
      setHistoryDialogOpen(false);
      setActiveReplay(replay);
    },
    [stopHistoryReplay],
  );

  const exitReplay = useCallback(
    (toHistory: boolean) => {
      setActiveReplay(null);
      setAuto(false);
      setHistoryDialogOpen(toHistory);
    },
    [setAuto],
  );

  const recordReplayAudio = useCallback(() => {
    if (!soundPlayerRef.current) throw new Error("Stage audio is unavailable");
    return soundPlayerRef.current.recordAudio();
  }, []);

  const confirmRevertHistory = useCallback(() => {
    if (confirmRevertUserIndex == null) {
      return;
    }
    setConfirmRevertUserIndex(null);
    setHistoryDialogOpen(false);
    void sendCommand({ payload: confirmRevertUserIndex, type: "revert-history" });
  }, [confirmRevertUserIndex, sendCommand]);

  useEffect(() => {
    if (state.replay) observedReplayIdRef.current = state.replay.id;
    if (
      activeReplay &&
      ((state.sessionId ?? "") !== activeReplay.snapshot.sessionId ||
        state.sessionClosedReason ||
        (state.replay && state.replay.id !== activeReplay.snapshot.id) ||
        (!state.replay && observedReplayIdRef.current === activeReplay.snapshot.id))
    ) {
      setActiveReplay(null);
      setHistoryDialogOpen(false);
    }
  }, [activeReplay, state.replay?.id, state.sessionId, state.sessionClosedReason]);

  useEffect(() => {
    if (!state.replay || activeReplay) return;
    let mounted = true;
    void getChatReplay(state.replay.id)
      .then((replay) => {
        if (mounted) setActiveReplay((current) => current ?? replay);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [state.replay?.id, activeReplay]);

  return {
    activeReplay,
    capturingReplay,
    closeHistoryDialog,
    confirmRevertHistory,
    confirmRevertUserIndex,
    exitCg,
    exitReplay,
    exportHistory,
    historyDialogOpen,
    historyExport,
    openHistoryDialog,
    recordReplayAudio,
    replayHistoryVoice,
    replaying: Boolean(activeReplay || state.replay),
    saveCg,
    savingCg,
    setConfirmRevertUserIndex,
    setHistoryDialogOpen,
    setHistoryExport,
    soundPlayerRef,
    startReplay,
  };
}
