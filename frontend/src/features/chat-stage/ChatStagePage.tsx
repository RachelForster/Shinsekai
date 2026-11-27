import "./chat-stage.css";
import { ChatStageDialogArea } from "./components/ChatStageDialogArea";
import { ChatStageDialogs } from "./components/ChatStageDialogs";
import { ChatStageRootOverlays } from "./components/ChatStageRootOverlays";
import { ChatStageScene } from "./components/ChatStageScene";
import { PluginPageOverlay } from "./components/PluginPageOverlay";
import { useChatStagePageController } from "./controllers/useChatStagePageController";

export function ChatStagePage() {
  const controller = useChatStagePageController();
  const { composer, desktop, historyReplay, pluginOverlay, stage } = controller;

  return (
    <>
      {pluginOverlay.overlayTarget ? (
        <PluginPageOverlay onClose={pluginOverlay.closePluginPageOverlay} target={pluginOverlay.overlayTarget} />
      ) : null}
      <main
        ref={composer.stageRef}
        className="chat-stage"
        data-mini-avatar={stage.miniAvatarActive ? "true" : "false"}
        data-viewport-vn={stage.vnDialogActive ? "true" : "false"}
        data-standalone={stage.standalone ? "true" : "false"}
        data-replaying={historyReplay.replaying ? "true" : undefined}
        data-replay-recording={historyReplay.capturingReplay ? "true" : undefined}
        data-background={stage.transparentBackground ? "transparent" : "media"}
        data-click-through={desktop.clickThroughEnabled ? "true" : "false"}
        data-stat-visible={stage.statsVisible && !stage.miniAvatarActive ? "true" : "false"}
        data-token-visible={stage.tokenUsageVisible && !stage.miniAvatarActive ? "true" : "false"}
        onContextMenuCapture={desktop.handleStageContextMenu}
        onFocusCapture={desktop.handleStageFocus}
        onPointerDownCapture={desktop.handleStagePointerDown}
        onPointerLeave={desktop.handleStagePointerLeave}
        onPointerMoveCapture={desktop.handleStagePointerMove}
        style={stage.stageStyle}
      >
        <ChatStageScene controller={controller} />
        <ChatStageDialogArea controller={controller} />
        <ChatStageDialogs controller={controller} />
      </main>
      <ChatStageRootOverlays controller={controller} />
    </>
  );
}
