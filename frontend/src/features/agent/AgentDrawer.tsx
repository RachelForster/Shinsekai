import { useEffect, useRef } from "react";
import { Bot, X } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import { AgentPanel } from "./AgentPanel";

export function AgentDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const panel = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const closeHandler = useRef(onClose);
  closeHandler.current = onClose;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    close.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeHandler.current();
      }
      if (event.key === "Tab" && panel.current) {
        const buttons = Array.from(
          panel.current.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], textarea:not(:disabled), [tabindex="0"]',
          ),
        ).filter((item) => item.offsetParent !== null);
        const first = buttons[0],
          last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, [open]);
  return (
    <div className="agent-drawer-layer" hidden={!open}>
      <button
        aria-label={t("common.close")}
        className="agent-drawer-scrim"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <aside aria-label={t("nav.assistant")} aria-modal="true" className="agent-drawer" ref={panel} role="dialog">
        <header className="agent-drawer__header">
          <h2>
            <Bot aria-hidden />
            {t("nav.assistant")}
          </h2>
          <button
            aria-label={t("common.close")}
            className="agent-drawer__close"
            onClick={onClose}
            ref={close}
            type="button"
          >
            <X aria-hidden />
          </button>
        </header>
        <AgentPanel enabled={open} onNavigate={onClose} />
      </aside>
    </div>
  );
}
