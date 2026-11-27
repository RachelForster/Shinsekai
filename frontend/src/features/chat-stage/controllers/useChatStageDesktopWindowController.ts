import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";

import { closeChatSurface } from "../../../shared/desktop/chatWindow";
import {
  setDesktopChatWindowMiniMode,
  setDesktopWindowAlwaysOnTop,
  syncDesktopChatWindowMiniLayout,
  type DesktopMiniDockSide,
} from "../../../shared/desktop/desktopApi";
import { closeChatRuntime } from "../../chat-startup/runtimeState";
import type { ChatStageState } from "../chatState";
import { useDesktopClickThrough } from "../hooks/useDesktopClickThrough";
import { useDesktopWindowDrag } from "../hooks/useDesktopWindowDrag";
import type { ActiveReplay } from "../replay/ReplayControls";
import type { ChatStageRuntimeConfig } from "../runtimeConfig";

export interface UseChatStageDesktopWindowControllerOptions {
  activeReplay: ActiveReplay | null;
  alwaysOnTop: boolean;
  cgVisible: boolean;
  desktopApp: boolean;
  miniAvatarActive: boolean;
  modalOpen: boolean;
  navigate: NavigateFunction;
  onBeforeEnterMiniAvatar: () => void;
  remoteMobileAccess: boolean;
  setRuntimeConfig: Dispatch<SetStateAction<ChatStageRuntimeConfig>>;
  standaloneDesktopWindow: boolean;
  state: ChatStageState;
  transparentBackground: boolean;
}

export function useChatStageDesktopWindowController({
  activeReplay,
  alwaysOnTop,
  cgVisible,
  desktopApp,
  miniAvatarActive,
  modalOpen,
  navigate,
  onBeforeEnterMiniAvatar,
  remoteMobileAccess,
  setRuntimeConfig,
  standaloneDesktopWindow,
  state,
  transparentBackground,
}: UseChatStageDesktopWindowControllerOptions) {
  const handleWindowDrag = useDesktopWindowDrag(standaloneDesktopWindow);
  const [miniDockSide, setMiniDockSide] = useState<DesktopMiniDockSide>("right");
  const [miniInputPinned, setMiniInputPinned] = useState(false);
  const wasMiniAvatarActiveRef = useRef(false);

  const clickThroughEnabled =
    standaloneDesktopWindow &&
    transparentBackground &&
    !cgVisible &&
    !modalOpen &&
    !(miniAvatarActive && miniInputPinned);

  const {
    handleStageContextMenu,
    handleStageFocus,
    handleStagePointerDown,
    handleStagePointerLeave,
    handleStagePointerMove,
  } = useDesktopClickThrough({
    clickThroughEnabled,
    standaloneDesktopWindow,
    transparentBackground,
  });

  useEffect(() => {
    if (!standaloneDesktopWindow || miniAvatarActive) {
      return;
    }
    void setDesktopWindowAlwaysOnTop(alwaysOnTop).catch((error) => {
      console.error("Desktop chat window always-on-top toggle failed", error);
    });
  }, [alwaysOnTop, miniAvatarActive, standaloneDesktopWindow]);

  const syncDesktopMiniDockSide = useCallback(() => {
    if (!standaloneDesktopWindow) {
      return;
    }
    void syncDesktopChatWindowMiniLayout()
      .then((layout) => {
        setMiniDockSide(layout.dockSide);
      })
      .catch((error) => {
        console.error("Desktop mini avatar layout sync failed", error);
      });
  }, [standaloneDesktopWindow]);

  useEffect(() => {
    if (!standaloneDesktopWindow) {
      wasMiniAvatarActiveRef.current = miniAvatarActive;
      return;
    }
    if (!miniAvatarActive && !wasMiniAvatarActiveRef.current) {
      return;
    }
    wasMiniAvatarActiveRef.current = miniAvatarActive;
    void setDesktopChatWindowMiniMode(miniAvatarActive, alwaysOnTop)
      .then((layout) => {
        setMiniDockSide(layout.dockSide);
      })
      .catch((error) => {
        console.error("Desktop chat window mini mode update failed", error);
      });
  }, [alwaysOnTop, miniAvatarActive, standaloneDesktopWindow]);

  const enterMiniAvatarMode = useCallback(() => {
    if (activeReplay || state.replay || remoteMobileAccess) {
      return;
    }
    onBeforeEnterMiniAvatar();
    setRuntimeConfig((current) => (current.miniAvatarMode ? current : { ...current, miniAvatarMode: true }));
  }, [activeReplay, onBeforeEnterMiniAvatar, remoteMobileAccess, setRuntimeConfig, state.replay]);

  const exitMiniAvatarMode = useCallback(() => {
    setRuntimeConfig((current) => (current.miniAvatarMode ? { ...current, miniAvatarMode: false } : current));
  }, [setRuntimeConfig]);

  const closeSurface = () =>
    closeChatSurface({
      closeRuntime: closeChatRuntime,
      webPath: state.story ? "/settings/templates?mode=story&view=library" : undefined,
      navigate,
      snapshot: state,
    });

  return {
    clickThroughEnabled,
    closeSurface,
    desktopApp,
    enterMiniAvatarMode,
    exitMiniAvatarMode,
    handleStageContextMenu,
    handleStageFocus,
    handleStagePointerDown,
    handleStagePointerLeave,
    handleStagePointerMove,
    handleWindowDrag,
    miniDockSide,
    setMiniInputPinned,
    standaloneDesktopWindow,
    syncDesktopMiniDockSide,
  };
}
