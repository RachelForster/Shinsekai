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
  dismissible?: boolean;
  footer?: ReactNode;
  headerActions?: ReactNode;
  onClose: () => void;
  open: boolean;
  title: string;
}

export function Dialog({
  bodyClassName = "",
  children,
  className = "",
  closeLabel = "Close",
  dismissible = true,
  footer,
  headerActions,
  onClose,
  open,
  title,
}: DialogProps) {
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    window.setTimeout(() => {
      if (dismissible) {
        closeButtonRef.current?.focus();
      } else {
        dialogRef.current?.focus();
      }
    }, 0);
    return () => previous?.focus();
  }, [dismissible, open]);

  if (!open) {
    return null;
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (dismissible && event.key === "Escape") {
      event.stopPropagation();
      onClose();
    }
  };

  return createPortal(
    <div className="dialog-backdrop" role="presentation">
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
      footer={
        <>
          <Button onClick={onCancel}>{cancelLabel}</Button>
          <Button onClick={onConfirm} variant={confirmVariant}>
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
