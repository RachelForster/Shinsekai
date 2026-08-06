import { useEffect, useRef, type Dispatch } from "react";

import { getChatSnapshot, subscribeChatEvents } from "../../../entities/chat/repository";
import { writeDesktopRestartDebugLog } from "../../../shared/desktop/desktopApi";
import type { ChatSnapshot } from "../../../shared/platform/types";
import type { ChatStageAction } from "../chatState";

function logChatStageEvents(message: string, data?: Record<string, unknown>) {
  if (data) {
    console.log(`[ChatStage] ${message}`, data);
  } else {
    console.log(`[ChatStage] ${message}`);
  }
  const suffix = data ? ` ${JSON.stringify(data)}` : "";
  void writeDesktopRestartDebugLog(`ChatStageEvents ${message}${suffix}`);
}

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
    logChatStageEvents("snapshot_fetch_start");
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          logChatStageEvents("snapshot_hydrated", {
            eventSeq: snapshot.eventSeq ?? 0,
            hasSessionId: Boolean(snapshot.sessionId),
            hasWsUrl: Boolean(snapshot.wsUrl),
            status: snapshot.status,
          });
          dispatch({ snapshot, type: "hydrate" });
        }
      })
      .catch((error) => {
        logChatStageEvents("snapshot_fetch_failed", {
          error: error instanceof Error ? error.message : String(error),
        });
        dispatch({ message: error instanceof Error ? error.message : loadFallbackMessage, type: "error" });
      });
    logChatStageEvents("subscribing_to_events");
    const unsubscribe = subscribeChatEvents((event) => {
      logChatStageEvents("event_received", {
        seq: event.seq,
        type: event.type,
      });
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
      logChatStageEvents("unsubscribed");
    };
  }, [dispatch, loadFallbackMessage, queueAnimatedDialog]);
}
