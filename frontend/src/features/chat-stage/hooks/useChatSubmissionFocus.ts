import { useCallback, useEffect, useReducer, useRef } from "react";

import type { ChatOption } from "../../../shared/platform/types";

type SubmissionTarget = { kind: "input" } | { kind: "options"; index: number };

/** Restore an available composer immediately; choices wait for the reply to finish. */
export function useChatSubmissionFocus({
  blocked,
  inputDisabled,
  options,
  replying,
  sessionId,
}: {
  blocked: boolean;
  inputDisabled: boolean;
  options: ChatOption[];
  replying: boolean;
  sessionId?: string;
}) {
  const stageRef = useRef<HTMLElement>(null);
  const preferred = useRef<SubmissionTarget | null>(null);
  const pending = useRef(false);
  const initializedOptions = useRef(false);
  const fallbackInput = useRef<HTMLElement | null>(null);
  const windowActive = useRef(true);
  const [revision, retry] = useReducer((value: number) => value + 1, 0);

  const rememberSubmission = useCallback((target: SubmissionTarget) => {
    preferred.current = target;
    pending.current = true;
    fallbackInput.current = null;
    retry();
  }, []);

  useEffect(() => {
    preferred.current = null;
    pending.current = false;
    initializedOptions.current = false;
    fallbackInput.current = null;
  }, [sessionId]);

  useEffect(() => {
    const blur = () => {
      windowActive.current = false;
    };
    const focus = () => {
      windowActive.current = true;
      retry();
    };
    const visibility = () => {
      if (document.visibilityState !== "hidden") retry();
    };
    // Editing or clicking after a fallback is a deliberate choice to stay there.
    const interact = () => {
      fallbackInput.current = null;
    };
    const stage = stageRef.current;
    window.addEventListener("blur", blur);
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", visibility);
    stage?.addEventListener("pointerdown", interact, true);
    stage?.addEventListener("input", interact, true);
    return () => {
      window.removeEventListener("blur", blur);
      window.removeEventListener("focus", focus);
      document.removeEventListener("visibilitychange", visibility);
      stage?.removeEventListener("pointerdown", interact, true);
      stage?.removeEventListener("input", interact, true);
    };
  }, []);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const goal = preferred.current;
    if ((goal?.kind === "input" && inputDisabled) || (goal?.kind !== "input" && replying)) {
      if (preferred.current) pending.current = true;
      return;
    }
    if (blocked || !windowActive.current || document.visibilityState === "hidden") return;
    const buttons = [...stage.querySelectorAll<HTMLButtonElement>(".options-layer__button")];
    const firstEnabled = buttons.find((button) => !button.disabled);
    const initialOptions = !preferred.current && !initializedOptions.current && firstEnabled;
    if (!pending.current && !initialOptions) return;
    const input = stage.querySelector<HTMLInputElement | HTMLTextAreaElement>(".input-layer__input:not(:disabled)");
    const selected = goal?.kind === "options" ? buttons[goal.index] : undefined;
    const target =
      goal?.kind === "input"
        ? (input ?? firstEnabled)
        : ((selected && !selected.disabled ? selected : firstEnabled) ?? input);
    if (!target || target.closest('[hidden], [aria-hidden="true"]')) return;
    if (initialOptions) initializedOptions.current = true;
    const active = document.activeElement;
    const fallback = goal?.kind === "options" && !firstEnabled;
    if ((active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) && active.value) {
      fallbackInput.current = null;
    }
    if (active === target) {
      pending.current = Boolean(fallback && active === fallbackInput.current);
      return;
    }
    if (
      active instanceof HTMLElement &&
      active.isConnected &&
      active !== document.body &&
      active !== document.documentElement &&
      active !== stage &&
      active !== fallbackInput.current &&
      !active.matches(".input-layer__send, .input-layer__quick-submit")
    )
      return;
    target.focus({ preventScroll: true });
    if (target instanceof HTMLButtonElement) target.scrollIntoView?.({ block: "nearest" });
    fallbackInput.current = fallback ? target : null;
    pending.current = fallback || (goal?.kind === "input" && !input);
  }, [blocked, inputDisabled, options, replying, revision, sessionId]);

  return { stageRef, rememberSubmission };
}
