import { useCallback, useEffect, useRef, useState, type FocusEvent } from "react";

export const autoHideDelayMs = 600;

export function useAutoHideRegion({
  active = true,
  enabled,
  forceVisible = false,
}: {
  active?: boolean;
  enabled: boolean;
  forceVisible?: boolean;
}) {
  const [visible, setVisible] = useState(true);
  const focusWithinRef = useRef(false);
  const hideTimerRef = useRef<number | null>(null);

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current != null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const show = useCallback(() => {
    clearHideTimer();
    setVisible(true);
  }, [clearHideTimer]);

  const scheduleHide = useCallback(() => {
    clearHideTimer();
    if (!active || !enabled || forceVisible || focusWithinRef.current) {
      setVisible(true);
      return;
    }
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null;
      setVisible(false);
    }, autoHideDelayMs);
  }, [active, clearHideTimer, enabled, forceVisible]);

  const handleBlur = useCallback(
    (event: FocusEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
        focusWithinRef.current = false;
        scheduleHide();
      }
    },
    [scheduleHide],
  );

  const handleFocus = useCallback(() => {
    focusWithinRef.current = true;
    show();
  }, [show]);

  useEffect(() => {
    if (!active) {
      clearHideTimer();
      focusWithinRef.current = false;
      setVisible(true);
    } else if (!enabled || forceVisible) {
      show();
    } else {
      scheduleHide();
    }
    return clearHideTimer;
  }, [active, clearHideTimer, enabled, forceVisible, scheduleHide, show]);

  return {
    handleBlur,
    handleFocus,
    scheduleHide,
    show,
    visible: !active || !enabled || forceVisible || visible,
  };
}
