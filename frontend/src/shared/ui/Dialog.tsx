import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import "./Dialog.css";
import { Button, type ButtonProps } from "./Button";
import { IconButton } from "./IconButton";

interface DialogProps {
  bodyClassName?: string;
  children: ReactNode;
  className?: string;
  closeLabel?: string;
  closeOnBackdrop?: boolean;
  dismissible?: boolean;
  footer?: ReactNode;
  headerActions?: ReactNode;
  onClose: () => void;
  open: boolean;
  title: string;
  trapFocus?: boolean;
}

export function Dialog({
  bodyClassName = "",
  children,
  className = "",
  closeLabel = "Close",
  closeOnBackdrop = false,
  dismissible = true,
  footer,
  headerActions,
  onClose,
  open,
  title,
  trapFocus = false,
}: DialogProps) {
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const timer = window.setTimeout(() => {
      if (dismissible) {
        closeButtonRef.current?.focus();
      } else {
        dialogRef.current?.focus();
      }
    }, 0);
    return () => {
      window.clearTimeout(timer);
      previous?.focus({ preventScroll: true });
    };
  }, [dismissible, open]);

  useEffect(() => {
    if (!open || !trapFocus) return;
    const focusDialog = () => (closeButtonRef.current ?? dialogRef.current)?.focus({ preventScroll: true });
    const containFocus = (event: FocusEvent) => {
      const dialog = dialogRef.current;
      if (dialog && !dialog.contains(event.target as Node)) focusDialog();
    };
    const outsideKey = (event: globalThis.KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog || dialog.contains(event.target as Node)) return;
      // Clicking a non-focusable image can leave keyboard focus on the body.
      if (event.key === "Tab") {
        event.preventDefault();
        focusDialog();
      } else if (dismissible && event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("focusin", containFocus);
    document.addEventListener("keydown", outsideKey);
    return () => {
      document.removeEventListener("focusin", containFocus);
      document.removeEventListener("keydown", outsideKey);
    };
  }, [dismissible, onClose, open, trapFocus]);

  if (!open) {
    return null;
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (trapFocus && event.key === "Tab") {
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      const first = focusable?.[0];
      const last = focusable?.[focusable.length - 1];
      if (!first || !last) {
        event.preventDefault();
        dialogRef.current?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    if (dismissible && event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  };

  return createPortal(
    <div
      className="dialog-backdrop"
      role="presentation"
      onClick={(event) => {
        if (closeOnBackdrop && dismissible && event.target === event.currentTarget) onClose();
      }}
    >
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className={["dialog", className].filter(Boolean).join(" ")}
        onKeyDown={onKeyDown}
        ref={dialogRef}
        role="dialog"
        tabIndex={dismissible ? undefined : -1}
      >
        <header className="dialog__header">
          <h2 className="dialog__title" id={titleId}>
            {title}
          </h2>
          <div className="dialog__header-actions">
            {headerActions}
            {dismissible ? (
              <IconButton label={closeLabel} onClick={onClose} ref={closeButtonRef}>
                <X aria-hidden className="icon-button__icon" />
              </IconButton>
            ) : null}
          </div>
        </header>
        <div className={["dialog__body", bodyClassName].filter(Boolean).join(" ")}>{children}</div>
        {footer ? <footer className="dialog__footer">{footer}</footer> : null}
      </section>
    </div>,
    document.body,
  );
}

interface AlertDialogProps {
  pending?: boolean;
  body: string;
  cancelLabel?: string;
  closeLabel?: string;
  confirmLabel?: string;
  confirmVariant?: ButtonProps["variant"];
  onCancel: () => void;
  onConfirm: () => void;
  open: boolean;
  title: string;
}

export function AlertDialog({
  pending = false,
  body,
  cancelLabel = "Cancel",
  closeLabel,
  confirmLabel = "Confirm",
  confirmVariant = "danger",
  onCancel,
  onConfirm,
  open,
  title,
}: AlertDialogProps) {
  return (
    <Dialog
      closeLabel={closeLabel}
      dismissible={!pending}
      footer={
        <>
          <Button disabled={pending} onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button loading={pending} onClick={onConfirm} variant={confirmVariant}>
            {confirmLabel}
          </Button>
        </>
      }
      onClose={onCancel}
      open={open}
      title={title}
    >
      {body}
    </Dialog>
  );
}
