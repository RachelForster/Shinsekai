import { useEffect, useRef, useState } from "react";

import { getKnowledgeStatus } from "../../entities/knowledge/repository";
import { useI18n } from "../../shared/i18n";
import type { Mem0Status, TaskSnapshot } from "../../shared/platform/types";
import { useToast } from "../../shared/ui";

/** Own model initialization, shared readiness checks, and loading dialog progress. */
export function useKnowledgeModelReadiness() {
  const { t } = useI18n();
  const { showToast } = useToast();
  const readinessCheck = useRef<Promise<boolean> | null>(null);
  const lifecycle = useRef<AbortController | null>(null);
  const [modelChecking, setModelChecking] = useState(false);
  const [modelLoadingOpen, setModelLoadingOpen] = useState(false);
  const [modelLoadingMessage, setModelLoadingMessage] = useState("");
  const [modelLoadingTask, setModelLoadingTask] = useState<TaskSnapshot | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifecycle.current = controller;
    return () => controller.abort();
  }, []);

  const ensureKnowledgeModelReady = (options?: { retry?: boolean }): Promise<boolean> => {
    if (readinessCheck.current) return readinessCheck.current;
    const signal = lifecycle.current?.signal;
    if (!signal || signal.aborted) return Promise.resolve(false);

    const showLoading = (status: Mem0Status) => {
      setModelLoadingTask(status.task ?? null);
      setModelLoadingMessage(
        status.modelCached ? t("character.memory.loadingModel") : t("character.memory.downloadingModel"),
      );
    };
    const waitForPoll = () =>
      new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          signal.removeEventListener("abort", finish);
          resolve();
        };
        const timer = setTimeout(finish, 1000);
        signal.addEventListener("abort", finish, { once: true });
      });

    const check = async () => {
      setModelChecking(true);
      setModelLoadingTask(null);
      // The first status request can take time while importing model dependencies.
      setModelLoadingMessage(t("character.memory.loadingModel"));
      setModelLoadingOpen(true);
      try {
        let status = await getKnowledgeStatus({ startLoading: true, retry: options?.retry ?? false });
        if (signal.aborted) return false;
        if (status.status === "loading" || status.status === "not_started") {
          showLoading(status);
        }
        if (status.status === "not_started") {
          status = await getKnowledgeStatus({ startLoading: true, retry: false });
          if (signal.aborted) return false;
        }
        while (status.status === "loading") {
          showLoading(status);
          await waitForPoll();
          if (signal.aborted) return false;
          status = await getKnowledgeStatus({ startLoading: false, retry: false });
          if (signal.aborted) return false;
        }
        if (status.status === "ready") return true;
        throw new Error(status.message || t("knowledge.loadFailed"));
      } catch (error) {
        if (signal.aborted) return false;
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("knowledge.loadFailed"),
          title: t("common.operationFailed"),
        });
        return false;
      } finally {
        if (!signal.aborted) {
          setModelChecking(false);
          setModelLoadingOpen(false);
        }
      }
    };

    readinessCheck.current = check().finally(() => {
      readinessCheck.current = null;
    });
    return readinessCheck.current;
  };

  return {
    ensureKnowledgeModelReady,
    modelChecking,
    modelLoadingOpen,
    modelLoadingMessage,
    modelLoadingTask,
    closeLoadingDialog: () => setModelLoadingOpen(false),
  };
}
