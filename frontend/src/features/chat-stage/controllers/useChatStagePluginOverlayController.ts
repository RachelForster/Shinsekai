import { useCallback, useEffect, useRef, useState } from "react";
import type { Location, NavigateFunction } from "react-router-dom";

import type { ChatAttachmentInput, ChatCommand } from "../../../shared/platform/types";
import type { PluginPageTarget } from "../../../shared/plugin/PluginSlot";
import type { ChatStageState } from "../chatState";
import { withChatRouteInputState } from "./chatStageRouteState";

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
    openPluginPage,
    overlayTarget,
  };
}
