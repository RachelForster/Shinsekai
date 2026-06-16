import {
  useCallback,
  useEffect,
  useRef,
  type FocusEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { getDesktopWindowCursorPosition, setDesktopWindowClickThrough } from "../../../shared/desktop/desktopApi";
import { isChatStageHitbox, isPointInsideChatStageHitbox } from "../chatStageUtils";
import { clickThroughGuardIntervalMs } from "../runtimeConfig";

export function useDesktopClickThrough({
  clickThroughEnabled,
  standaloneDesktopWindow,
  transparentBackground,
}: {
  clickThroughEnabled: boolean;
  standaloneDesktopWindow: boolean;
  transparentBackground: boolean;
}) {
  const clickThroughIgnoredRef = useRef(false);
  const clickThroughGuardIntervalRef = useRef<number | null>(null);
  const clickThroughGuardPollingRef = useRef(false);

  const stopClickThroughGuard = useCallback(() => {
    if (clickThroughGuardIntervalRef.current == null) {
      return;
    }
    window.clearInterval(clickThroughGuardIntervalRef.current);
    clickThroughGuardIntervalRef.current = null;
  }, []);

  const applyClickThroughIgnored = useCallback((ignore: boolean) => {
    if (clickThroughIgnoredRef.current === ignore) {
      return;
    }
    clickThroughIgnoredRef.current = ignore;
    void setDesktopWindowClickThrough(ignore).catch((error) => {
      console.error("Desktop chat window click-through update failed", error);
    });
  }, []);

  const disableClickThrough = useCallback(() => {
    stopClickThroughGuard();
    applyClickThroughIgnored(false);
  }, [applyClickThroughIgnored, stopClickThroughGuard]);

  const startClickThroughGuard = useCallback(() => {
    if (clickThroughGuardIntervalRef.current != null) {
      return;
    }
    const pollCursor = async () => {
      if (clickThroughGuardPollingRef.current) {
        return;
      }
      clickThroughGuardPollingRef.current = true;
      try {
        const cursor = await getDesktopWindowCursorPosition();
        if (isPointInsideChatStageHitbox(cursor.x, cursor.y)) {
          disableClickThrough();
        }
      } catch (error) {
        console.error("Desktop chat window cursor guard failed", error);
        disableClickThrough();
      } finally {
        clickThroughGuardPollingRef.current = false;
      }
    };
    clickThroughGuardIntervalRef.current = window.setInterval(pollCursor, clickThroughGuardIntervalMs);
    void pollCursor();
  }, [disableClickThrough]);

  const enableClickThrough = useCallback(() => {
    applyClickThroughIgnored(true);
    startClickThroughGuard();
  }, [applyClickThroughIgnored, startClickThroughGuard]);

  const setClickThroughIgnored = useCallback(
    (ignore: boolean) => {
      if (ignore) {
        enableClickThrough();
      } else {
        disableClickThrough();
      }
    },
    [disableClickThrough, enableClickThrough],
  );

  useEffect(() => {
    if (transparentBackground) {
      document.documentElement.dataset.chatStageTransparent = "true";
      document.body.dataset.chatStageTransparent = "true";
    } else {
      delete document.documentElement.dataset.chatStageTransparent;
      delete document.body.dataset.chatStageTransparent;
    }
    return () => {
      delete document.documentElement.dataset.chatStageTransparent;
      delete document.body.dataset.chatStageTransparent;
    };
  }, [transparentBackground]);

  useEffect(() => {
    if (!standaloneDesktopWindow) {
      return;
    }
    if (!clickThroughEnabled) {
      setClickThroughIgnored(false);
    }
    return () => {
      setClickThroughIgnored(false);
    };
  }, [clickThroughEnabled, setClickThroughIgnored, standaloneDesktopWindow]);

  useEffect(
    () => () => {
      stopClickThroughGuard();
    },
    [stopClickThroughGuard],
  );

  const handleStagePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled) {
        return;
      }
      if (isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false);
        return;
      }
      setClickThroughIgnored(true);
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled || isChatStageHitbox(event.target)) {
        return;
      }
      setClickThroughIgnored(true);
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerLeave = useCallback(() => {
    if (standaloneDesktopWindow) {
      setClickThroughIgnored(false);
    }
  }, [setClickThroughIgnored, standaloneDesktopWindow]);

  const handleStageFocus = useCallback(
    (event: FocusEvent<HTMLElement>) => {
      if (clickThroughEnabled && isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false);
      }
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStageContextMenu = useCallback((event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
  }, []);

  return {
    handleStageContextMenu,
    handleStageFocus,
    handleStagePointerDown,
    handleStagePointerLeave,
    handleStagePointerMove,
  };
}
