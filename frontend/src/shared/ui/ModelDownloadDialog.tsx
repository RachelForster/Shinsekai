import type { TaskSnapshot } from "../platform/types";
import { AsyncButton, Button } from "./Button";
import { Dialog } from "./Dialog";
import { TaskProgress } from "./TaskProgress";

import "./ModelDownloadDialog.css";

export type ModelDownloadDialogState = "checking" | "confirm" | "downloading" | "error" | "success";

export interface ModelDownloadDialogDetail {
  label: string;
  value: string;
}

interface ModelDownloadDialogProps {
  cancelLabel: string;
  closeLabel: string;
  confirmLabel: string;
  description?: string;
  details?: readonly ModelDownloadDialogDetail[];
  error?: string | null;
  onClose: () => void;
  onConfirm?: () => void;
  onRetry?: () => void;
  open: boolean;
  retryLabel?: string;
  state: ModelDownloadDialogState;
  statusMessage?: string;
  task?: TaskSnapshot | null;
  title: string;
}

export function ModelDownloadDialog({
  cancelLabel,
  closeLabel,
  confirmLabel,
  description,
  details = [],
  error,
  onClose,
  onConfirm,
  onRetry,
  open,
  retryLabel,
  state,
  statusMessage,
  task = null,
  title,
}: ModelDownloadDialogProps) {
  const busy = state === "checking" || state === "downloading";
  const footer = (() => {
    if (state === "confirm") {
      return (
        <>
          <Button onClick={onClose}>{cancelLabel}</Button>
          <Button onClick={onConfirm} variant="primary">
            {confirmLabel}
          </Button>
        </>
      );
    }
    if (state === "error" && onRetry && retryLabel) {
      return (
        <>
          <Button onClick={onClose}>{closeLabel}</Button>
          <Button onClick={onRetry} variant="primary">
            {retryLabel}
          </Button>
        </>
      );
    }
    return (
      <AsyncButton loading={busy} onClick={onClose}>
        {busy ? statusMessage || closeLabel : closeLabel}
      </AsyncButton>
    );
  })();

  return (
    <Dialog
      className="model-download-dialog"
      closeLabel={closeLabel}
      footer={footer}
      onClose={onClose}
      open={open}
      title={title}
    >
      <div className="model-download-dialog__content">
        {description ? <p className="model-download-dialog__description">{description}</p> : null}
        {details.length ? (
          <dl className="model-download-dialog__details">
            {details.map((detail) => (
              <div className="model-download-dialog__detail" key={`${detail.label}:${detail.value}`}>
                <dt>{detail.label}</dt>
                <dd>{detail.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {statusMessage ? (
          <div className="model-download-dialog__status" role="status" aria-live="polite">
            {statusMessage}
          </div>
        ) : null}
        {task ? <TaskProgress logLimit={4} task={task} /> : null}
        {error ? (
          <div className="model-download-dialog__error" role="alert">
            {error}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
