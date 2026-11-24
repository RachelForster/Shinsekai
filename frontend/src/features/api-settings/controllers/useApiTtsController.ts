import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  cancelTtsBundleDownload,
  downloadTtsBundle,
  getTtsBundleRecommendation,
  ttsBundleRecommendationQueryKey,
} from "../../../entities/config/repository";
import type { ApiConfig } from "../../../entities/config/types";
import { useI18n } from "../../../shared/i18n";
import type { TaskSnapshot, TtsBundleDownloadResult, TtsBundleKind } from "../../../shared/platform/types";
import { useToast } from "../../../shared/ui";
import {
  applyDownloadedTtsBundle,
  applyTtsProviderDefaults,
  isTaskCancelledError,
  isTaskRunning,
  normalizeTtsProvider,
  syncCompactRatioDraft,
} from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";
import { formatTtsBundleFailure } from "./apiSettingsValidation";

export function useApiTtsController(ctx: ApiSettingsPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const ttsBundleRecommendationQuery = useQuery({
    queryFn: getTtsBundleRecommendation,
    queryKey: ttsBundleRecommendationQueryKey,
    staleTime: 300_000,
  });
  const [ttsBundleKind, setTtsBundleKind] = useState<TtsBundleKind>("genie");
  const [ttsBundleKindTouched, setTtsBundleKindTouched] = useState(false);
  const [ttsBundleDialogOpen, setTtsBundleDialogOpen] = useState(false);
  const [ttsBundleError, setTtsBundleError] = useState<string | null>(null);
  const [ttsBundleTask, setTtsBundleTask] = useState<TaskSnapshot<TtsBundleDownloadResult> | null>(null);

  const ttsBundleMutation = useMutation({
    mutationFn: () => downloadTtsBundle({ kind: ttsBundleKind }, { onTaskUpdate: setTtsBundleTask }),
    onError(error) {
      if (isTaskCancelledError(error)) {
        return;
      }
      const message = formatTtsBundleFailure(error, t);
      setTtsBundleError(message);
      showToast({
        kind: "error",
        message,
        title: t("api.tts.bundleTitle"),
      });
    },
    onMutate() {
      setTtsBundleError(null);
      setTtsBundleTask(null);
    },
    onSuccess(result) {
      setTtsBundleDialogOpen(false);
      setTtsBundleError(null);
      ctx.setDraft((current) => (current ? applyDownloadedTtsBundle(current, result) : current));
      showToast({
        kind: "success",
        message: t("api.tts.bundleDone", { path: result.path }),
        title: t("api.tts.bundleTitle"),
      });
    },
  });

  const ttsBundleCancelMutation = useMutation({
    mutationFn: () => {
      if (!ttsBundleTask?.id) {
        throw new Error(t("api.tts.bundleCancelUnavailable"));
      }
      return cancelTtsBundleDownload(ttsBundleTask.id);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.tts.bundleCancelFailed"),
        title: t("api.tts.bundleTitle"),
      });
    },
    onSuccess(task) {
      setTtsBundleTask(task);
      showToast({
        kind: "success",
        title: task.status === "cancelled" ? t("api.tts.bundleCancelled") : t("api.tts.bundleCancelRequested"),
      });
    },
  });

  useEffect(() => {
    const recommendation = ttsBundleRecommendationQuery.data;
    if (!recommendation || ttsBundleKindTouched || ttsBundleMutation.isPending) {
      return;
    }
    setTtsBundleKind(recommendation.kind);
  }, [ttsBundleKindTouched, ttsBundleMutation.isPending, ttsBundleRecommendationQuery.data]);

  const canCancelDownload =
    ttsBundleMutation.isPending && isTaskRunning(ttsBundleTask) && !ttsBundleTask?.cancelRequested;

  const openTtsBundleDialog = useCallback(() => {
    setTtsBundleDialogOpen(true);
    setTtsBundleError(null);
    void ttsBundleRecommendationQuery.refetch();
  }, [ttsBundleRecommendationQuery]);

  const updateTtsDraftFromSchema = useCallback(
    (nextDraft: ApiConfig) => {
      const syncedDraft = syncCompactRatioDraft(nextDraft);
      if (normalizeTtsProvider(nextDraft.tts_provider) !== normalizeTtsProvider(ctx.draft.tts_provider)) {
        ctx.setDraft(
          applyTtsProviderDefaults(syncedDraft, ctx.installedTtsBundlePathForProvider(nextDraft.tts_provider)),
        );
        return;
      }
      ctx.setDraft(syncedDraft);
    },
    [ctx.draft.tts_provider, ctx.installedTtsBundlePathForProvider, ctx.setDraft],
  );

  return {
    cancelPending: ttsBundleCancelMutation.isPending,
    canCancelDownload,
    closeDialog: () => setTtsBundleDialogOpen(false),
    dialogOpen: ttsBundleDialogOpen,
    downloadPending: ttsBundleMutation.isPending,
    error: ttsBundleError,
    kind: ttsBundleKind,
    onCancelDownload: () => ttsBundleCancelMutation.mutate(),
    onKindChange: (kind: TtsBundleKind) => {
      setTtsBundleKindTouched(true);
      setTtsBundleKind(kind);
    },
    onStartDownload: () => ttsBundleMutation.mutate(),
    openTtsBundleDialog,
    recommendation: ttsBundleRecommendationQuery.data,
    recommendationError: ttsBundleRecommendationQuery.isError,
    recommendationLoading: ttsBundleRecommendationQuery.isLoading,
    task: ttsBundleTask,
    updateTtsDraftFromSchema,
  };
}
