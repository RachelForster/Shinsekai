import { useCallback, useEffect, useRef, useState, type Dispatch } from "react";

import { getChatSnapshot, subscribeChatEvents } from "../../../entities/chat/repository";
import type { ChatSnapshot } from "../../../shared/platform/types";
import type { ChatStageAction } from "../chatState";

export function useChatStageEvents({
  dispatch,
  eventSeq,
  sessionId,
  loadFallbackMessage,
  queueAnimatedDialog,
}: {
  dispatch: Dispatch<ChatStageAction>;
  eventSeq: number;
  sessionId?: string;
  loadFallbackMessage: string;
  queueAnimatedDialog: (input: { characterName?: string; html?: string; text?: string }) => void;
}) {
  const eventSeqRef = useRef(0);
  eventSeqRef.current = eventSeq;
  const cancelRef = useRef<(() => void) | null>(null);
  const [subscriptionRevision, setSubscriptionRevision] = useState(0);
  const replaceSession = useCallback(
    (snapshot: ChatSnapshot) => {
      // Stop old events and pending hydration before accepting the new session.
      cancelRef.current?.();
      eventSeqRef.current = snapshot.eventSeq ?? 0;
      dispatch({ type: "replaceSession", snapshot, receivedAt: performance.now() });
      setSubscriptionRevision((revision) => revision + 1);
    },
    [dispatch],
  );

  useEffect(() => {
    let mounted = true;
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          dispatch({ snapshot, type: "hydrate", receivedAt: performance.now() });
        }
      })
      .catch((error) => {
        if (mounted) dispatch({ message: error instanceof Error ? error.message : loadFallbackMessage, type: "error" });
      });
    const unsubscribe = subscribeChatEvents((event) => {
      if (!mounted) return;
      if (event.type === "dialog.end" && event.seq > eventSeqRef.current) {
        if (!event.isSystem || event.speaker.trim()) {
          queueAnimatedDialog({
            characterName: event.speaker,
            html: event.fullHtml,
          });
        }
      }
      dispatch({ event, type: "event", receivedAt: performance.now() });
    });
    const cancel = () => {
      if (!mounted) return;
      mounted = false;
      unsubscribe();
    };
    cancelRef.current = cancel;
    return cancel;
  }, [dispatch, loadFallbackMessage, queueAnimatedDialog, sessionId, subscriptionRevision]);
  return { replaceSession };
}
