import { useEffect, useRef, type Dispatch } from "react";

import { getChatSnapshot, subscribeChatEvents } from "../../../entities/chat/repository";
import type { ChatSnapshot } from "../../../shared/platform/types";
import type { ChatStageAction } from "../chatState";

export function useChatStageEvents({
  dispatch,
  eventSeq,
  loadFallbackMessage,
  queueAnimatedDialog,
}: {
  dispatch: Dispatch<ChatStageAction>;
  eventSeq: number;
  loadFallbackMessage: string;
  queueAnimatedDialog: (input: { characterName?: string; html?: string; text?: string }) => void;
}) {
  const eventSeqRef = useRef(0);
  eventSeqRef.current = eventSeq;

  useEffect(() => {
    let mounted = true;
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          dispatch({ snapshot, type: "hydrate" });
        }
      })
      .catch((error) => {
        dispatch({ message: error instanceof Error ? error.message : loadFallbackMessage, type: "error" });
      });
    const unsubscribe = subscribeChatEvents((event) => {
      if (event.type === "dialog.end" && event.seq > eventSeqRef.current) {
        if (!event.isSystem || event.speaker.trim()) {
          queueAnimatedDialog({
            characterName: event.speaker,
            html: event.fullHtml,
          });
        }
      }
      dispatch({ event, type: "event" });
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, [dispatch, loadFallbackMessage, queueAnimatedDialog]);
}
