import { useEffect, useRef, useState, type RefObject } from "react";

import { isTauriDesktop } from "../../../shared/desktop/desktopApi";
import { isDesktopWindowExpanded, subscribeDesktopWindowResize } from "../../../shared/desktop/windowViewport";
import type { StageViewportState } from "../dialogViewportLayout";

function isBrowserFullscreen(): boolean {
  if (typeof document !== "undefined" && Boolean(document.fullscreenElement)) {
    return true;
  }
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return Boolean(window.matchMedia("(display-mode: fullscreen)").matches);
  }
  return false;
}

function readViewportSize(observedSize: { width: number; height: number } | null): {
  width: number;
  height: number;
} {
  if (observedSize && observedSize.width > 0 && observedSize.height > 0) {
    return observedSize;
  }
  if (typeof window === "undefined") {
    return { width: 1280, height: 820 };
  }
  return {
    width: window.innerWidth || document.documentElement?.clientWidth || 1280,
    height: window.innerHeight || document.documentElement?.clientHeight || 820,
  };
}

export function useStageViewport(stageRef: RefObject<HTMLElement | null>): StageViewportState {
  const desktopExpandedRef = useRef(false);
  const observedSizeRef = useRef<{ width: number; height: number } | null>(null);
  const [viewport, setViewport] = useState<StageViewportState>(() => {
    const size = readViewportSize(null);
    return {
      width: size.width,
      height: size.height,
      expanded: isBrowserFullscreen(),
    };
  });

  useEffect(() => {
    let disposed = false;

    const commit = () => {
      if (disposed) {
        return;
      }
      const size = readViewportSize(observedSizeRef.current);
      const expanded = isBrowserFullscreen() || desktopExpandedRef.current;
      setViewport((current) =>
        current.width === size.width && current.height === size.height && current.expanded === expanded
          ? current
          : { width: size.width, height: size.height, expanded },
      );
    };

    const syncDesktopExpanded = () => {
      if (!isTauriDesktop()) {
        return;
      }
      void isDesktopWindowExpanded().then((expanded) => {
        if (disposed || desktopExpandedRef.current === expanded) {
          return;
        }
        desktopExpandedRef.current = expanded;
        commit();
      });
    };

    const handleWindowResize = () => {
      observedSizeRef.current = null;
      commit();
      syncDesktopExpanded();
    };

    const handleFullscreenChange = () => {
      commit();
    };

    window.addEventListener("resize", handleWindowResize);
    document.addEventListener("fullscreenchange", handleFullscreenChange);

    const mediaQuery = typeof window.matchMedia === "function" ? window.matchMedia("(display-mode: fullscreen)") : null;
    mediaQuery?.addEventListener?.("change", handleFullscreenChange);

    const stageElement = stageRef.current;
    const resizeObserver =
      stageElement && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver((entries) => {
            const rect = entries[0]?.contentRect;
            if (rect && rect.width > 0 && rect.height > 0) {
              observedSizeRef.current = {
                width: Math.round(rect.width),
                height: Math.round(rect.height),
              };
              commit();
            }
          })
        : null;
    if (stageElement && resizeObserver) {
      resizeObserver.observe(stageElement);
    }

    let unlistenDesktopResize: (() => void) | undefined;
    if (isTauriDesktop()) {
      syncDesktopExpanded();
      void subscribeDesktopWindowResize(() => {
        syncDesktopExpanded();
        commit();
      }).then((unlisten) => {
        if (disposed) {
          unlisten();
        } else {
          unlistenDesktopResize = unlisten;
        }
      });
    }

    return () => {
      disposed = true;
      window.removeEventListener("resize", handleWindowResize);
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      mediaQuery?.removeEventListener?.("change", handleFullscreenChange);
      resizeObserver?.disconnect();
      unlistenDesktopResize?.();
    };
  }, [stageRef]);

  return viewport;
}
