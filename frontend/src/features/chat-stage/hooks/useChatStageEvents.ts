import { useCallback, useEffect, useRef, useState, type Dispatch } from "react";

import { getChatSnapshot, subscribeChatEvents } from "../../../entities/chat/repository";
import { onPlatformModeChange } from "../../../shared/platform/platform";
import type { ChatSnapshot, PluginBehaviorEvent } from "../../../shared/platform/types";
import { emptyChatState, type ChatStageAction } from "../chatState";

const MAX_DELIVERED_BEHAVIOR_SEQ_WINDOW = 256;

export function useChatStageEvents({
  dispatch,
  eventSeq,
  sessionId,
  loadFallbackMessage,
  onPluginBehaviorEvent,
  onPluginBehaviorSessionReset,
  queueAnimatedDialog,
  showDialogImmediately,
}: {
  dispatch: Dispatch<ChatStageAction>;
  eventSeq: number;
  sessionId?: string;
  loadFallbackMessage: string;
  onPluginBehaviorEvent?: (event: PluginBehaviorEvent) => void;
  onPluginBehaviorSessionReset?: () => void;
  queueAnimatedDialog: (input: { characterName?: string; html?: string; text?: string }) => void;
  showDialogImmediately?: () => void;
}) {
  const eventSeqRef = useRef(0);
  const highestSeqRef = useRef(0);
  const watermarkSessionIdRef = useRef<string | undefined>(sessionId);
  const deliveredBehaviorSeqsRef = useRef(new Set<number>());
  const prunedFloorSeqRef = useRef(0);
  const onPluginBehaviorEventRef = useRef(onPluginBehaviorEvent);
  onPluginBehaviorEventRef.current = onPluginBehaviorEvent;
  const onPluginBehaviorSessionResetRef = useRef(onPluginBehaviorSessionReset);
  onPluginBehaviorSessionResetRef.current = onPluginBehaviorSessionReset;
  const cancelRef = useRef<(() => void) | null>(null);
  const [subscriptionRevision, setSubscriptionRevision] = useState(0);

  const resetSessionWatermark = useCallback((nextSessionId?: string, nextSeq = 0) => {
    watermarkSessionIdRef.current = nextSessionId?.trim() || undefined;
    eventSeqRef.current = nextSeq;
    highestSeqRef.current = nextSeq;
    deliveredBehaviorSeqsRef.current.clear();
    prunedFloorSeqRef.current = 0;
    onPluginBehaviorSessionResetRef.current?.();
  }, []);

  if (sessionId && watermarkSessionIdRef.current && sessionId !== watermarkSessionIdRef.current) {
    resetSessionWatermark(sessionId, eventSeq);
  } else if (sessionId && !watermarkSessionIdRef.current) {
    watermarkSessionIdRef.current = sessionId;
  }

  eventSeqRef.current = eventSeq;
  if (eventSeq > highestSeqRef.current) {
    highestSeqRef.current = eventSeq;
  }

  const hasDeliveredBehaviorSeq = useCallback((seq: number) => {
    return seq > 0 && (seq <= prunedFloorSeqRef.current || deliveredBehaviorSeqsRef.current.has(seq));
  }, []);

  const markDeliveredBehaviorSeq = useCallback((seq: number) => {
    if (seq <= 0) {
      return;
    }
    const set = deliveredBehaviorSeqsRef.current;
    set.add(seq);
    if (set.size > MAX_DELIVERED_BEHAVIOR_SEQ_WINDOW) {
      const sorted = Array.from(set).sort((a, b) => a - b);
      const dropCount = sorted.length - Math.floor(MAX_DELIVERED_BEHAVIOR_SEQ_WINDOW / 2);
      const droppedMax = sorted[dropCount - 1] ?? 0;
      for (let i = 0; i < dropCount; i += 1) {
        set.delete(sorted[i]);
      }
      if (droppedMax > prunedFloorSeqRef.current) {
        prunedFloorSeqRef.current = droppedMax;
      }
    }
  }, []);

  const consumeSnapshot = useCallback(
    (snapshot: ChatSnapshot, { forceReset = false }: { forceReset?: boolean } = {}) => {
      const snapshotSessionId = snapshot.sessionId?.trim() || undefined;
      const snapshotSeq =
        typeof snapshot.eventSeq === "number" && Number.isFinite(snapshot.eventSeq) ? snapshot.eventSeq : 0;
      const sessionChanged =
        forceReset ||
        Boolean(
          snapshotSessionId && watermarkSessionIdRef.current && snapshotSessionId !== watermarkSessionIdRef.current,
        );

      if (sessionChanged) {
        resetSessionWatermark(snapshotSessionId, 0);
      } else if (snapshotSessionId && !watermarkSessionIdRef.current) {
        watermarkSessionIdRef.current = snapshotSessionId;
      }

      if (!sessionChanged && snapshotSeq < highestSeqRef.current) {
        return;
      }

      const outbox = [...(snapshot.pluginBehaviorEvents ?? [])].sort((a, b) => a.seq - b.seq);
      for (const item of outbox) {
        if (item.seq > 0 && !hasDeliveredBehaviorSeq(item.seq)) {
          markDeliveredBehaviorSeq(item.seq);
          onPluginBehaviorEventRef.current?.({
            eventType: item.eventType,
            payload: item.payload ?? {},
            pluginId: item.pluginId,
            seq: item.seq,
          });
        }
      }

      highestSeqRef.current = Math.max(highestSeqRef.current, snapshotSeq);
      if (sessionChanged) {
        eventSeqRef.current = snapshotSeq;
      }
    },
    [hasDeliveredBehaviorSeq, markDeliveredBehaviorSeq, resetSessionWatermark],
  );

  const replaceSession = useCallback(
    (snapshot: ChatSnapshot) => {
      // Stop old events and pending hydration before accepting the new session.
      cancelRef.current?.();
      consumeSnapshot(snapshot, { forceReset: true });
      dispatch({ type: "replaceSession", snapshot, receivedAt: performance.now() });
      setSubscriptionRevision((revision) => revision + 1);
    },
    [consumeSnapshot, dispatch],
  );

  useEffect(() => {
    return onPlatformModeChange(() => {
      // Unsubscribe from the previous platform and reset sequence state before rebinding.
      cancelRef.current?.();
      resetSessionWatermark(undefined, 0);
      dispatch({
        type: "replaceSession",
        snapshot: { ...emptyChatState, effectImage: null, eventSeq: 0 },
        receivedAt: performance.now(),
      });
      setSubscriptionRevision((revision) => revision + 1);
    });
  }, [dispatch, resetSessionWatermark]);

  useEffect(() => {
    let mounted = true;
    getChatSnapshot()
      .then((snapshot: ChatSnapshot) => {
        if (mounted) {
          consumeSnapshot(snapshot);
          dispatch({ snapshot, type: "hydrate", receivedAt: performance.now() });
        }
      })
      .catch((error) => {
        if (mounted) dispatch({ message: error instanceof Error ? error.message : loadFallbackMessage, type: "error" });
      });
    const unsubscribe = subscribeChatEvents((event) => {
      if (!mounted) return;
      if (event.type === "snapshot") {
        consumeSnapshot(event.snapshot);
        dispatch({ event, type: "event", receivedAt: performance.now() });
        return;
      }
      if (
        event.type === "presentation.restore" &&
        event.seq > eventSeqRef.current &&
        ("dialogHtml" in event.presentation || "dialogText" in event.presentation)
      ) {
        showDialogImmediately?.();
      }
      if (event.type === "dialog.end" && event.animate !== false && event.seq > eventSeqRef.current) {
        if (!event.isSystem || event.speaker.trim()) {
          queueAnimatedDialog({
            characterName: event.speaker,
            html: event.fullHtml,
          });
        }
      }
      if (
        event.type === "plugin.behavior.event" &&
        (event.seq === 0 || (event.seq > highestSeqRef.current && !hasDeliveredBehaviorSeq(event.seq)))
      ) {
        markDeliveredBehaviorSeq(event.seq);
        onPluginBehaviorEventRef.current?.({
          eventType: event.eventType,
          payload: event.payload ?? {},
          pluginId: event.pluginId,
          seq: event.seq,
        });
      }
      if (event.seq > highestSeqRef.current) {
        highestSeqRef.current = event.seq;
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
  }, [
    consumeSnapshot,
    dispatch,
    hasDeliveredBehaviorSeq,
    loadFallbackMessage,
    markDeliveredBehaviorSeq,
    queueAnimatedDialog,
    showDialogImmediately,
    sessionId,
    subscriptionRevision,
  ]);
  return { replaceSession };
}
