import { useEffect } from "react";

export function useChatStageKeyboardShortcuts({
  disabled,
  onAdvance,
  onToggleAuto,
}: {
  disabled: boolean;
  onAdvance: () => void;
  onToggleAuto: () => void;
}) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (disabled) {
        return;
      }
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        onAdvance();
      } else if (event.key === "a" || event.key === "A") {
        onToggleAuto();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [disabled, onAdvance, onToggleAuto]);
}
