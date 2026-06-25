import {
  useCallback,
  useEffect,
  useRef,
  type FocusEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  getDesktopWindowCursorPosition,
  setDesktopWindowClickThrough,
  writeDesktopRestartDebugLog,
} from "../../../shared/desktop/desktopApi";
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

  const applyClickThroughIgnored = useCallback((ignore: boolean, reason: string) => {
    if (clickThroughIgnoredRef.current === ignore) {
      return;
    }
    clickThroughIgnoredRef.current = ignore;
    void writeDesktopRestartDebugLog(`ChatStage click_through_ignore=${ignore} reason=${reason}`);
    void setDesktopWindowClickThrough(ignore).catch((error) => {
      console.error("Desktop chat window click-through update failed", error);
    });
  }, []);

  const disableClickThrough = useCallback(
    (reason: string) => {
      stopClickThroughGuard();
      applyClickThroughIgnored(false, reason);
    },
    [applyClickThroughIgnored, stopClickThroughGuard],
  );

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
          disableClickThrough("guard-hitbox");
        }
      } catch (error) {
        console.error("Desktop chat window cursor guard failed", error);
        disableClickThrough("guard-error");
      } finally {
        clickThroughGuardPollingRef.current = false;
      }
    };
    clickThroughGuardIntervalRef.current = window.setInterval(pollCursor, clickThroughGuardIntervalMs);
    void pollCursor();
  }, [disableClickThrough]);

  const enableClickThrough = useCallback(
    (reason: string) => {
      applyClickThroughIgnored(true, reason);
      startClickThroughGuard();
    },
    [applyClickThroughIgnored, startClickThroughGuard],
  );

  const setClickThroughIgnored = useCallback(
    (ignore: boolean, reason: string) => {
      if (ignore) {
        enableClickThrough(reason);
      } else {
        disableClickThrough(reason);
      }
    },
    [disableClickThrough, enableClickThrough],
  );

  useEffect(() => {
    void writeDesktopRestartDebugLog(
      `ChatStage click_through_state enabled=${clickThroughEnabled} standalone=${standaloneDesktopWindow} transparent=${transparentBackground}`,
    );
  }, [clickThroughEnabled, standaloneDesktopWindow, transparentBackground]);

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
    setClickThroughIgnored(clickThroughEnabled, clickThroughEnabled ? "enabled-transparent-stage" : "disabled-stage");
    return () => {
      setClickThroughIgnored(false, "cleanup");
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
        setClickThroughIgnored(false, "pointer-hitbox");
        return;
      }
      setClickThroughIgnored(true, "pointer-transparent");
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!clickThroughEnabled) {
        return;
      }
      setClickThroughIgnored(!isChatStageHitbox(event.target), "pointer-down");
    },
    [clickThroughEnabled, setClickThroughIgnored],
  );

  const handleStagePointerLeave = useCallback(() => {
    if (!standaloneDesktopWindow) {
      return;
    }
    setClickThroughIgnored(
      clickThroughEnabled,
      clickThroughEnabled ? "pointer-leave-transparent" : "pointer-leave-disabled",
    );
  }, [clickThroughEnabled, setClickThroughIgnored, standaloneDesktopWindow]);

  const handleStageFocus = useCallback(
    (event: FocusEvent<HTMLElement>) => {
      if (clickThroughEnabled && isChatStageHitbox(event.target)) {
        setClickThroughIgnored(false, "focus-hitbox");
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
