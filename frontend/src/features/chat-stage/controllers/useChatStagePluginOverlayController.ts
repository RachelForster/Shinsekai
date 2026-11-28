import { useCallback, useEffect, useRef, useState } from "react";
import type { Location, NavigateFunction } from "react-router-dom";

import type { ChatAttachmentInput, ChatCommand, PluginBehaviorEvent } from "../../../shared/platform/types";
import type { PluginPageTarget } from "../../../shared/plugin/PluginSlot";
import type { ChatStageState } from "../chatState";
import { withChatRouteInputState } from "./chatStageRouteState";

const MAX_QUEUED_BEHAVIOR_EVENTS_PER_PLUGIN = 32;

export interface UseChatStagePluginOverlayControllerOptions {
  inputAttachments: ChatAttachmentInput[];
  inputDraft: string;
  location: Location;
  navigate: NavigateFunction;
  pluginPagePresentations: ChatStageState["pluginPagePresentations"];
  sendCommand: (command: ChatCommand) => Promise<void>;
}

export function useChatStagePluginOverlayController({
  inputAttachments,
  inputDraft,
  location,
  navigate,
  pluginPagePresentations,
  sendCommand,
}: UseChatStagePluginOverlayControllerOptions) {
  const [overlayTarget, setOverlayTarget] = useState<PluginPageTarget | null>(null);
  const locallyDismissedPresentationRef = useRef<string | null>(null);
  const behaviorEventListenersRef = useRef(new Map<(event: PluginBehaviorEvent) => void, string | undefined>());
  const pendingBehaviorEventsByPluginRef = useRef(new Map<string, PluginBehaviorEvent[]>());

  const emitBehaviorEvent = useCallback((event: PluginBehaviorEvent) => {
    const matchingListeners: Array<(event: PluginBehaviorEvent) => void> = [];
    for (const [listener, listenerPluginId] of behaviorEventListenersRef.current.entries()) {
      if (listenerPluginId === undefined || listenerPluginId === event.pluginId) {
        matchingListeners.push(listener);
      }
    }
    if (matchingListeners.length > 0) {
      for (const listener of matchingListeners) {
        listener(event);
      }
      return;
    }
    const existing = pendingBehaviorEventsByPluginRef.current.get(event.pluginId) ?? [];
    if (event.seq > 0 && existing.some((item) => item.seq === event.seq)) {
      return;
    }
    const nextQueue = [...existing, event].slice(-MAX_QUEUED_BEHAVIOR_EVENTS_PER_PLUGIN);
    pendingBehaviorEventsByPluginRef.current.set(event.pluginId, nextQueue);
  }, []);

  const subscribeBehaviorEvents = useCallback((listener: (event: PluginBehaviorEvent) => void, pluginId?: string) => {
    behaviorEventListenersRef.current.set(listener, pluginId);
    if (pluginId !== undefined) {
      const queued = pendingBehaviorEventsByPluginRef.current.get(pluginId);
      if (queued?.length) {
        pendingBehaviorEventsByPluginRef.current.delete(pluginId);
        for (const event of queued) {
          listener(event);
        }
      }
    } else {
      for (const [queuedPluginId, queued] of Array.from(pendingBehaviorEventsByPluginRef.current.entries())) {
        pendingBehaviorEventsByPluginRef.current.delete(queuedPluginId);
        for (const event of queued) {
          listener(event);
        }
      }
    }
    return () => {
      behaviorEventListenersRef.current.delete(listener);
    };
  }, []);

  const resetPendingBehaviorEvents = useCallback(() => {
    pendingBehaviorEventsByPluginRef.current.clear();
  }, []);

  useEffect(() => {
    const presentation = pluginPagePresentations?.at(-1);
    if (!presentation) {
      locallyDismissedPresentationRef.current = null;
      setOverlayTarget((current) => (current?.presentationId ? null : current));
      return;
    }
    const presentationKey = `${presentation.pluginId}\0${presentation.presentationId}`;
    if (locallyDismissedPresentationRef.current === presentationKey) {
      setOverlayTarget((current) => (current?.presentationId ? null : current));
      return;
    }
    setOverlayTarget((current) => {
      if (
        current?.pluginId === presentation.pluginId &&
        current.presentationId === presentation.presentationId &&
        current.payload === presentation.payload
      ) {
        return current;
      }
      return {
        mode: presentation.mode,
        pageId: presentation.pageId,
        payload: presentation.payload,
        pluginId: presentation.pluginId,
        presentationId: presentation.presentationId,
      };
    });
  }, [pluginPagePresentations]);

  const closePluginPageOverlay = useCallback(() => {
    const current = overlayTarget;
    setOverlayTarget(null);
    if (current?.pluginId) {
      pendingBehaviorEventsByPluginRef.current.delete(current.pluginId);
    }
    if (!current?.presentationId) {
      return;
    }
    locallyDismissedPresentationRef.current = `${current.pluginId}\0${current.presentationId}`;
    void sendCommand({
      payload: {
        pluginId: current.pluginId,
        presentationId: current.presentationId,
      },
      type: "dismiss-plugin-page",
    });
  }, [overlayTarget, sendCommand]);

  const openPluginPage = useCallback(
    ({ mode, pageId, pluginId }: PluginPageTarget) => {
      if (mode === "overlay") {
        setOverlayTarget({ mode, pageId, pluginId });
        return;
      }
      navigate(
        { pathname: "/settings/plugins", search: location.search },
        {
          state: {
            pageId,
            pluginId,
            returnTo: {
              hash: location.hash,
              pathname: location.pathname,
              search: location.search,
              state: withChatRouteInputState(location.state, {
                inputAttachments,
                inputDraft,
              }),
            },
          },
        },
      );
    },
    [inputAttachments, inputDraft, location.hash, location.pathname, location.search, location.state, navigate],
  );

  return {
    closePluginPageOverlay,
    emitBehaviorEvent,
    openPluginPage,
    overlayTarget,
    resetPendingBehaviorEvents,
    subscribeBehaviorEvents,
  };
}
