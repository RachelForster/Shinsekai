import { createContext, useCallback, useContext, useMemo, useReducer } from "react";
import type { ReactNode } from "react";

type ToastKind = "success" | "error" | "info";

export interface ToastPayload {
  kind?: ToastKind;
  message?: string;
  title: string;
}

interface ToastItem extends ToastPayload {
  id: string;
  kind: ToastKind;
}

interface ToastContextValue {
  showToast: (payload: ToastPayload) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

type ToastAction = { type: "push"; toast: ToastItem } | { type: "remove"; id: string };

function toastReducer(state: ToastItem[], action: ToastAction) {
  switch (action.type) {
    case "push":
      return [...state, action.toast].slice(-4);
    case "remove":
      return state.filter((toast) => toast.id !== action.id);
    default:
      return state;
  }
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, dispatch] = useReducer(toastReducer, []);

  const showToast = useCallback((payload: ToastPayload) => {
    const id = globalThis.crypto?.randomUUID?.() ?? String(Date.now());
    const toast: ToastItem = { kind: payload.kind ?? "info", ...payload, id };
    dispatch({ toast, type: "push" });
    window.setTimeout(() => dispatch({ id, type: "remove" }), 4500);
  }, []);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="toast-region">
        {toasts.map((toast) => (
          <article className={`toast toast--${toast.kind}`} key={toast.id}>
            <p className="toast__title">{toast.title}</p>
            {toast.message ? <p className="toast__message">{toast.message}</p> : null}
          </article>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return value;
}
