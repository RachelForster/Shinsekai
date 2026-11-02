import { useMemo } from "react";

import { useI18n } from "../../shared/i18n";
import type { MessageKey } from "../../shared/i18n";
import type { ChatSnapshot, TaskSnapshot } from "../../shared/platform/types";
import { Button, Dialog, TaskProgress } from "../../shared/ui";

import "./ChatInitializationDialog.css";

interface ChatInitializationDialogProps {
  error?: string | null;
  onClose: () => void;
  open: boolean;
  pending: boolean;
  task?: TaskSnapshot<ChatSnapshot> | null;
}

const phaseMessageKeys: Record<string, MessageKey> = {
  cancelled: "chat.init.phase.cancelled",
  completed: "chat.init.phase.completed",
  failed: "chat.init.phase.failed",
  finalizing: "chat.init.phase.finalizing",
  memory: "chat.init.phase.memory",
  plugins: "chat.init.phase.plugins",
  preparing: "chat.init.phase.preparing",
  ready: "chat.init.phase.finalizing",
  runtime: "chat.init.phase.runtime",
  tts: "chat.init.phase.tts",
};

function phaseFamilyOf(phase: string) {
  const normalized = phase.trim().toLowerCase();
  if (phaseMessageKeys[normalized]) {
    return normalized;
  }
  if (normalized.includes("memory")) {
    return "memory";
  }
  if (normalized.includes("tts") || normalized.includes("voice")) {
    return "tts";
  }
  if (normalized.includes("plugin") || normalized.includes("hook")) {
    return "plugins";
  }
  if (normalized.includes("final") || normalized.includes("ready") || normalized.includes("complete")) {
    return "finalizing";
  }
  if (
    normalized.includes("config") ||
    normalized.includes("i18n") ||
    normalized.includes("args") ||
    normalized.includes("template")
  ) {
    return "preparing";
  }
  return "runtime";
}

export function ChatInitializationDialog({
  error,
  onClose,
  open,
  pending,
  task = null,
}: ChatInitializationDialogProps) {
  const { t } = useI18n();
  const phase = String(task?.phase || "preparing");
  const phaseFamily = phaseFamilyOf(phase);
  const phaseLabel = t(phaseMessageKeys[phaseFamily]);
  const displayTask = useMemo(
    () =>
      task
        ? { ...task, phase: phaseLabel }
        : pending
          ? {
              logs: [],
              message: t("chat.init.waitingForProgress"),
              phase: phaseLabel,
              progress: null,
              status: "running",
            }
          : null,
    [pending, phaseLabel, t, task],
  );
  const taskLabels =
    phaseFamily === "memory" ? { message: "", phase: "", status: t("chat.init.inProgress") } : undefined;
  const visibleError =
    error || task?.errorUserMessage || task?.error || (task?.status === "failed" ? task.message : "");

  return (
    <Dialog
      className="chat-initialization-dialog"
      closeLabel={t("common.close")}
      dismissible={!pending}
      footer={pending ? null : <Button onClick={onClose}>{t("common.close")}</Button>}
      onClose={onClose}
      open={open}
      title={t("chat.init.title")}
    >
      <div className="chat-initialization-dialog__content">
        <div className="chat-initialization-dialog__hero">
          <div className="chat-initialization-dialog__mascot" aria-hidden>
            <img alt="" draggable={false} src="/chat-init-catgirl.gif" />
          </div>
          <div className="chat-initialization-dialog__copy">
            <strong>{pending ? phaseLabel : t("chat.init.failed")}</strong>
            <p>{t("chat.init.description")}</p>
          </div>
        </div>
        {displayTask ? <TaskProgress labels={taskLabels} logLimit={5} task={displayTask} /> : null}
        {visibleError ? (
          <div className="chat-initialization-dialog__error" role="alert">
            {visibleError}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
