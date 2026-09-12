import type { ReactNode } from "react";
import { Check, ChevronLeft, ChevronRight, MoreHorizontal, X } from "lucide-react";
import type { MessageKey } from "../../shared/i18n";

interface CompactReminderCardProps {
  portrait: ReactNode;
  name: string;
  message: string;
  time: string;
  index: number;
  count: number;
  busy: boolean;
  error: string;
  voiceControls?: ReactNode;
  t: (key: MessageKey) => string;
  onClose: () => void;
  onDismiss: () => void;
  onManage: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onRetry: () => void;
}

export function CompactReminderCard(props: CompactReminderCardProps) {
  const { t } = props;
  return (
    <main className="reminder-panel reminder-panel--compact" aria-label={t("reminder.title")}>
      {props.portrait}
      <section className="reminder-card__body">
        <header className="reminder-card__header">
          <h1>{props.name}</h1>
          <button aria-label={t("reminder.close")} title={t("reminder.close")} onClick={props.onClose}>
            <X size={15} />
          </button>
        </header>
        <p className="reminder-card__speech" aria-live="polite" tabIndex={0}>
          {props.message}
        </p>
        {props.error && (
          <div className="reminder-panel__error" role="alert">
            <span>{props.error}</span>
            <button onClick={props.onRetry}>{t("reminder.retry")}</button>
          </div>
        )}
        <footer className="reminder-card__actions">
          {props.count > 1 ? (
            <div className="reminder-card__pager">
              <button aria-label={t("reminder.previous")} title={t("reminder.previous")} onClick={props.onPrevious}>
                <ChevronLeft size={13} />
              </button>
              <span>
                {props.index + 1}/{props.count}
              </span>
              <button aria-label={t("reminder.next")} title={t("reminder.next")} onClick={props.onNext}>
                <ChevronRight size={13} />
              </button>
            </div>
          ) : (
            <span className="reminder-card__time">{props.time}</span>
          )}
          <div>
            {props.voiceControls}
            {props.count > 0 && (
              <button
                aria-label={t("reminder.done")}
                title={t("reminder.done")}
                disabled={props.busy}
                onClick={props.onDismiss}
              >
                <Check size={15} />
              </button>
            )}
            <button
              aria-label={t("reminder.manage")}
              title={t("reminder.manage")}
              disabled={props.busy}
              onClick={props.onManage}
            >
              <MoreHorizontal size={16} />
            </button>
          </div>
        </footer>
      </section>
    </main>
  );
}
