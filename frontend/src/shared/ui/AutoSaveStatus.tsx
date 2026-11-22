import type { KeyboardEvent } from "react";
import { AlertCircle, Check, Clock, Loader2, RotateCcw, X } from "lucide-react";

import type { AutoSavePhase } from "../hooks/useDebouncedAutoSave";
import { useI18n } from "../i18n";
import { AsyncButton, Button } from "./Button";
import "./AutoSaveStatus.css";

export interface AutoSaveStatusProps {
  errorMessage?: string;
  onRetry?: () => void;
  pendingIdentity?: boolean;
  phase: AutoSavePhase;
}

export function AutoSaveStatus({ errorMessage, onRetry, pendingIdentity = false, phase }: AutoSaveStatusProps) {
  const { t } = useI18n();

  if (phase === "error") {
    return (
      <div className="autosave-status autosave-status--error" role="status" title={errorMessage || undefined}>
        <AlertCircle aria-hidden className="autosave-status__icon" />
        <span className="autosave-status__label">{t("autosave.failed")}</span>
        {onRetry ? (
          <Button
            className="autosave-status__retry"
            icon={<RotateCcw aria-hidden className="button__icon" />}
            onClick={onRetry}
            variant="ghost"
          >
            {t("common.retry")}
          </Button>
        ) : null}
      </div>
    );
  }

  if (phase === "saving") {
    return (
      <span className="autosave-status autosave-status--saving" role="status">
        <Loader2 aria-hidden className="autosave-status__icon autosave-status__icon--spin" />
        <span className="autosave-status__label">{t("autosave.saving")}</span>
      </span>
    );
  }

  if (phase === "pending") {
    return (
      <span className="autosave-status autosave-status--pending" role="status">
        <Clock aria-hidden className="autosave-status__icon" />
        <span className="autosave-status__label">{t("autosave.pending")}</span>
      </span>
    );
  }

  if (pendingIdentity) {
    return (
      <span className="autosave-status autosave-status--identity" role="status">
        <Clock aria-hidden className="autosave-status__icon" />
        <span className="autosave-status__label">{t("identity.pendingBadge")}</span>
      </span>
    );
  }

  return (
    <span
      className={`autosave-status ${phase === "saved" ? "autosave-status--saved" : "autosave-status--idle"}`}
      role="status"
    >
      <Check aria-hidden className="autosave-status__icon" />
      <span className="autosave-status__label">{t(phase === "saved" ? "autosave.saved" : "autosave.idle")}</span>
    </span>
  );
}

export interface InlineIdentityConfirmProps {
  confirmDisabled?: boolean;
  fieldLabel: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  visible: boolean;
}

export function InlineIdentityConfirm({
  confirmDisabled = false,
  fieldLabel,
  loading = false,
  onCancel,
  onConfirm,
  visible,
}: InlineIdentityConfirmProps) {
  const { t } = useI18n();

  if (!visible) {
    return null;
  }

  return (
    <span className="identity-inline-actions" title={t("identity.shortcutHint")}>
      <AsyncButton
        aria-label={`${t("identity.confirm")}: ${fieldLabel}`}
        className="identity-inline-actions__btn"
        disabled={confirmDisabled}
        icon={<Check aria-hidden className="button__icon" />}
        loading={loading}
        onClick={onConfirm}
        tooltip={t("identity.shortcutHint")}
        variant="primary"
      >
        {t("identity.confirm")}
      </AsyncButton>
      <Button
        aria-label={`${t("identity.cancel")}: ${fieldLabel}`}
        className="identity-inline-actions__btn"
        disabled={loading}
        icon={<X aria-hidden className="button__icon" />}
        onClick={onCancel}
        tooltip={t("identity.cancel")}
        variant="ghost"
      >
        {t("identity.cancel")}
      </Button>
    </span>
  );
}

export function handleIdentityKeyDown(
  event: KeyboardEvent<HTMLInputElement>,
  options: {
    canConfirm: boolean;
    isDirty: boolean;
    onCancel: () => void;
    onConfirm: () => void;
  },
) {
  if (!options.isDirty || event.nativeEvent.isComposing) {
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    if (options.canConfirm) {
      options.onConfirm();
    }
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    options.onCancel();
  }
}
