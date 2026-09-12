import type { ReactNode } from "react";
import { Check, ChevronLeft, ChevronRight, MoreHorizontal, X } from "lucide-react";
import { reminderPanelCopy } from "../../shared/i18n/reminderPanelCopy";

interface CompactReminderCardProps {
  portrait: ReactNode;
  name: string;
  message: string;
  time: string;
  index: number;
  count: number;
  busy: boolean;
  error: string;
  text: (typeof reminderPanelCopy)[keyof typeof reminderPanelCopy];
  onClose: () => void;
  onDismiss: () => void;
  onManage: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onRetry: () => void;
}

export function CompactReminderCard(props: CompactReminderCardProps) {
  const { text } = props;
  return (
    <main className="reminder-panel reminder-panel--compact" aria-label={text.title}>
      {props.portrait}
      <section className="reminder-card__body">
        <header className="reminder-card__header">
          <h1>{props.name}</h1>
          <button aria-label={text.close} title={text.close} onClick={props.onClose}>
            <X size={15} />
          </button>
        </header>
        <p className="reminder-card__speech" aria-live="polite" tabIndex={0}>
          {props.message}
        </p>
        {props.error && (
          <div className="reminder-panel__error" role="alert">
            <span>{props.error}</span>
            <button onClick={props.onRetry}>{text.retry}</button>
          </div>
        )}
        <footer className="reminder-card__actions">
          {props.count > 1 ? (
            <div className="reminder-card__pager">
              <button aria-label={text.previous} title={text.previous} onClick={props.onPrevious}>
                <ChevronLeft size={13} />
              </button>
              <span>
                {props.index + 1}/{props.count}
              </span>
              <button aria-label={text.next} title={text.next} onClick={props.onNext}>
                <ChevronRight size={13} />
              </button>
            </div>
          ) : (
            <span className="reminder-card__time">{props.time}</span>
          )}
          <div>
            {props.count > 0 && (
              <button aria-label={text.done} title={text.done} disabled={props.busy} onClick={props.onDismiss}>
                <Check size={15} />
              </button>
            )}
            <button aria-label={text.manage} title={text.manage} disabled={props.busy} onClick={props.onManage}>
              <MoreHorizontal size={16} />
            </button>
          </div>
        </footer>
      </section>
    </main>
  );
}
