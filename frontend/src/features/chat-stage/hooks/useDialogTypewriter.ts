import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ChatRuntimeStatus } from "../../../shared/platform/types";
import {
  buildDialogTypewriterSource,
  renderDialogTypewriterRichFrame,
  type DialogTypewriterDirection,
} from "../dialogTypewriter";

const AUTO_ADVANCE_DELAY_MS = 1600;

export function useDialogTypewriter({
  auto,
  characterName,
  dialogVisible,
  html,
  onAutoAdvance,
  optionsVisible,
  status,
  text,
  textDirection,
  typewriterCps,
}: {
  auto: boolean;
  characterName?: string;
  dialogVisible: boolean;
  html?: string;
  onAutoAdvance: () => void;
  optionsVisible: boolean;
  status: ChatRuntimeStatus;
  text: string;
  textDirection: DialogTypewriterDirection;
  typewriterCps: number;
}) {
  const [visibleDialogCharacters, setVisibleDialogCharacters] = useState(0);
  const pendingAnimatedDialogKeyRef = useRef<string | null>(null);
  const onAutoAdvanceRef = useRef(onAutoAdvance);

  useEffect(() => {
    onAutoAdvanceRef.current = onAutoAdvance;
  }, [onAutoAdvance]);

  const dialogSource = useMemo(
    () =>
      buildDialogTypewriterSource({
        characterName,
        html,
        text,
      }),
    [characterName, html, text],
  );
  const dialogTotalCharacters =
    textDirection === "rtl" ? dialogSource.totalRtlCharacters : dialogSource.totalCharacters;
  const displayedDialog = useMemo(
    () => renderDialogTypewriterRichFrame(dialogSource, visibleDialogCharacters, textDirection),
    [dialogSource, textDirection, visibleDialogCharacters],
  );
  const typingDialog = visibleDialogCharacters < dialogTotalCharacters;

  const queueAnimatedDialog = useCallback((input: { characterName?: string; html?: string; text?: string }) => {
    pendingAnimatedDialogKeyRef.current = buildDialogTypewriterSource(input).cacheKey;
    setVisibleDialogCharacters(0);
  }, []);

  const showFullDialog = useCallback(() => {
    setVisibleDialogCharacters(dialogTotalCharacters);
  }, [dialogTotalCharacters]);

  useEffect(() => {
    const pendingKey = pendingAnimatedDialogKeyRef.current;
    if (pendingKey === dialogSource.cacheKey) {
      pendingAnimatedDialogKeyRef.current = null;
      return;
    }
    setVisibleDialogCharacters(dialogTotalCharacters);
  }, [dialogSource.cacheKey, dialogTotalCharacters]);

  useEffect(() => {
    if (visibleDialogCharacters >= dialogTotalCharacters) {
      return;
    }
    const delayMs = Math.max(16, Math.round(1000 / Math.max(1, typewriterCps)));
    const timeoutId = window.setTimeout(() => {
      setVisibleDialogCharacters((current) => Math.min(dialogTotalCharacters, current + 1));
    }, delayMs);
    return () => window.clearTimeout(timeoutId);
  }, [dialogTotalCharacters, typewriterCps, visibleDialogCharacters]);

  useEffect(() => {
    if (!auto || typingDialog) {
      return;
    }
    if (!dialogVisible || optionsVisible || !dialogTotalCharacters) {
      return;
    }
    if (status === "generating" || status === "streaming") {
      return;
    }
    const timeoutId = window.setTimeout(() => onAutoAdvanceRef.current(), AUTO_ADVANCE_DELAY_MS);
    return () => window.clearTimeout(timeoutId);
  }, [auto, dialogSource.cacheKey, dialogTotalCharacters, dialogVisible, optionsVisible, status, typingDialog]);

  return {
    dialogSource,
    dialogTotalCharacters,
    displayedDialog,
    queueAnimatedDialog,
    showFullDialog,
    typingDialog,
  };
}
