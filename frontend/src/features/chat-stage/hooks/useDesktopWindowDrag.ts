import { useCallback, type MouseEvent } from "react";

import { startDesktopWindowDrag } from "../../../shared/desktop/desktopApi";

export function useDesktopWindowDrag(enabled: boolean) {
  return useCallback(
    (event: MouseEvent<HTMLElement>) => {
      if (!enabled || event.button !== 0) {
        return;
      }
      event.preventDefault();
      void startDesktopWindowDrag().catch((error) => {
        console.error("Desktop chat window drag failed", error);
      });
    },
    [enabled],
  );
}
