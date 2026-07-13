import { useEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode, type RefObject } from "react";
import { X } from "lucide-react";

import { IconButton } from "../../../shared/ui";

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function focusableElements(root: HTMLElement) {
  return Array.from(root.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) => !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true",
  );
}

function focusInitialElement(dialog: HTMLElement, initialFocusRef?: RefObject<HTMLElement | null>) {
  const target = initialFocusRef?.current ?? focusableElements(dialog)[0] ?? dialog;
  target.focus();
}

export function ChatStageModal({
  backdropClassName,
  children,
  closeLabel,
  dialogClassName,
  dialogId,
  eyebrow,
  labelledBy,
  onClose,
  open,
  summary,
  title,
}: {
  backdropClassName: string;
  children: ReactNode;
  closeLabel: string;
  dialogClassName: string;
  dialogId?: string;
  eyebrow?: ReactNode;
  labelledBy: string;
  onClose: () => void;
  open: boolean;
  summary?: ReactNode;
  title: ReactNode;
}) {
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.setTimeout(() => {
      const dialog = dialogRef.current;
      if (dialog) {
        focusInitialElement(dialog, closeButtonRef);
      }
    }, 0);
    return () => previous?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const backdrop = backdropRef.current;
    const siblings = backdrop?.parentElement
      ? Array.from(backdrop.parentElement.children).filter((element) => element !== backdrop)
      : [];
    const previousState = siblings
      .filter((element): element is HTMLElement => element instanceof HTMLElement)
      .map((element) => ({
        ariaHidden: element.getAttribute("aria-hidden"),
        element,
        inert: element.inert,
      }));
    for (const { element } of previousState) {
      element.inert = true;
      element.setAttribute("aria-hidden", "true");
    }
    return () => {
      for (const { ariaHidden, element, inert } of previousState) {
        element.inert = inert;
        if (ariaHidden == null) {
          element.removeAttribute("aria-hidden");
        } else {
          element.setAttribute("aria-hidden", ariaHidden);
        }
      }
    };
  }, [open]);

  if (!open) {
    return null;
  }

  const handleBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    const focusable = focusableElements(dialog);
    if (!focusable.length) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const active = document.activeElement as HTMLElement | null;
    const activeIndex = active ? focusable.indexOf(active) : -1;
    if (event.shiftKey && activeIndex <= 0) {
      event.preventDefault();
      focusable[focusable.length - 1]?.focus();
    } else if (!event.shiftKey && activeIndex === focusable.length - 1) {
      event.preventDefault();
      focusable[0]?.focus();
    }
  };

  return (
    <div
      ref={backdropRef}
      className={`chat-stage-modal-backdrop ${backdropClassName}`}
      data-chat-stage-hitbox="true"
      onMouseDown={handleBackdropMouseDown}
      role="presentation"
    >
      <section
        ref={dialogRef}
        aria-labelledby={labelledBy}
        aria-modal="true"
        className={`chat-stage-modal ${dialogClassName}`}
        id={dialogId}
        onKeyDown={handleKeyDown}
        role="dialog"
        tabIndex={-1}
      >
        <header className="chat-stage-modal__header">
          <div className="chat-stage-modal__heading">
            {eyebrow ? <span className="chat-stage-modal__eyebrow">{eyebrow}</span> : null}
            <h2 className="chat-stage-modal__title" id={labelledBy}>
              {title}
            </h2>
            {summary ? <div className="chat-stage-modal__summary">{summary}</div> : null}
          </div>
          <IconButton className="chat-stage-modal__close" label={closeLabel} onClick={onClose} ref={closeButtonRef}>
            <X aria-hidden className="icon-button__icon" />
          </IconButton>
        </header>
        {children}
      </section>
    </div>
  );
}
