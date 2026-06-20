import { useEffect, type RefObject } from "react";

export function useDismissableLayer({
  active,
  onDismiss,
  rootRef,
}: {
  active: boolean;
  onDismiss: () => void;
  rootRef: RefObject<HTMLElement | null>;
}) {
  useEffect(() => {
    if (!active) {
      return;
    }
    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        onDismiss();
      }
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        onDismiss();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [active, onDismiss, rootRef]);
}
