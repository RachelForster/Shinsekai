import { useEffect, useRef } from "react";
import type { ChatCommand } from "../../../shared/platform/types";

/** F8 is local to the focused chat window and does not consume typing keys. */
export function useHoldToTalk({
  enabled,
  disabled,
  onCommand,
}: {
  enabled: boolean;
  disabled: boolean;
  onCommand: (command: ChatCommand) => void | Promise<void>;
}) {
  const queue = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    if (!enabled || disabled) return;
    let held = false;
    let finishing = false;
    const send = (type: ChatCommand["type"]) => {
      // A fast key release must still reach the server after its start command.
      queue.current = queue.current.catch(() => {}).then(() => onCommand({ type }));
      return queue.current;
    };
    const finish = (cancel: boolean) => {
      if (!held) return;
      held = false;
      finishing = true;
      void send(cancel ? "cancel-asr-hold" : "finish-asr-hold")
        .catch(() => {})
        .finally(() => {
          finishing = false;
        });
    };
    const keyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && held) {
        event.preventDefault();
        finish(true);
        return;
      }
      if (
        event.code !== "F8" ||
        event.repeat ||
        held ||
        finishing ||
        event.isComposing ||
        event.ctrlKey ||
        event.altKey ||
        event.metaKey ||
        event.shiftKey ||
        document.hidden
      )
        return;
      event.preventDefault();
      held = true;
      void send("begin-asr-hold").catch(() => {
        finish(true);
      });
    };
    const keyUp = (event: KeyboardEvent) => {
      if (event.code !== "F8" || !held) return;
      event.preventDefault();
      finish(false);
    };
    const cancel = () => finish(true);
    const visibilityChanged = () => {
      if (document.hidden) cancel();
    };
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    window.addEventListener("blur", cancel);
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      cancel();
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      window.removeEventListener("blur", cancel);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [enabled, disabled, onCommand]);
}
