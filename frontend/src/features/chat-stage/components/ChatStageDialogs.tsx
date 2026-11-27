import type { ChatStagePageController } from "../controllers/useChatStagePageController";
import { HistoryExportDialog } from "../replay/HistoryExportDialog";
import { ChatConfigDialog } from "./ChatConfigDialog";
import { HistoryDialog } from "./HistoryDialog";
import { ScreenSharePreflightDialog } from "./ScreenSharePreflightDialog";
import { ScreenShareSettingsDialog } from "./ScreenShareSettingsDialog";

export interface ChatStageDialogsProps {
  controller: ChatStagePageController;
}

export function ChatStageDialogs({ controller }: ChatStageDialogsProps) {
  const {
    commands,
    desktop,
    historyReplay,
    interaction,
    modals,
    pluginOverlay,
    runtime,
    screenShare,
    stage,
    state,
    viewModel,
  } = controller;

  return (
    <>
      <HistoryDialog
        recordAudio={historyReplay.recordReplayAudio}
        replayDisabled={stage.replayDisabled}
        onStartReplay={historyReplay.startReplay}
        entries={state.historyEntries ?? []}
        loading={commands.historyLoading}
        onClear={() => void commands.sendCommand({ type: "clear-history" })}
        onClose={historyReplay.closeHistoryDialog}
        onExportImage={(blob) => historyReplay.exportHistory(blob, "png")}
        onRefresh={() => {
          void commands.refreshHistory();
        }}
        onReplayVoice={(voiceId) => void historyReplay.replayHistoryVoice(voiceId)}
        onRevert={(userIndex) => historyReplay.setConfirmRevertUserIndex(userIndex)}
        onSaveVoice={(voiceId) => void commands.sendCommand({ payload: voiceId, type: "save-history-voice" })}
        onToggleVoiceArchive={(enabled) => void commands.sendCommand({ payload: enabled, type: "set-voice-archive" })}
        open={historyReplay.historyDialogOpen && !historyReplay.historyExport}
        sessionId={state.sessionId}
        userDisplayName={viewModel.userDisplayName}
        voiceArchiveEnabled={state.voiceArchiveEnabled === true}
      />
      {historyReplay.historyExport && (
        <HistoryExportDialog
          result={historyReplay.historyExport}
          onClose={() => historyReplay.setHistoryExport(undefined)}
        />
      )}
      {screenShare.screenSettingsOpen && screenShare.screenShareStream ? (
        <ScreenShareSettingsDialog
          currentScene={state.perception?.rpCache?.currentScene}
          ocrEnabled={Boolean(state.perception?.ocrEnabled)}
          onClose={() => screenShare.setScreenSettingsOpen(false)}
          onScopeChange={screenShare.changeOcrScope}
          playbackAudio={screenShare.playbackAudio}
          proactiveEnabled={state.perception?.proactiveEnabled ?? true}
          scope={screenShare.ocrScope}
          stream={screenShare.screenShareStream}
        />
      ) : null}
      {screenShare.screenSharePreflightOpen ? (
        <ScreenSharePreflightDialog
          errorDetail={screenShare.screenSharePreflight.errorDetail}
          errorKind={screenShare.screenSharePreflight.errorKind}
          health={screenShare.screenSharePreflight.health}
          installingPackage={screenShare.screenSharePreflight.installingPackage}
          localServer={screenShare.screenSharePreflight.localServer}
          onCancel={screenShare.screenSharePreflight.close}
          onPrepareAndStart={() => void screenShare.screenSharePreflight.prepareAndStart()}
          onProceedToShare={screenShare.screenSharePreflight.proceedToShare}
          onRetry={() => void screenShare.screenSharePreflight.retry()}
          open={screenShare.screenSharePreflightOpen}
          phase={screenShare.screenSharePreflight.phase}
          setup={screenShare.screenSharePreflight.setup}
          setupTask={screenShare.screenSharePreflight.setupTask}
          status={screenShare.screenSharePreflight.status}
        />
      ) : null}
      <ChatConfigDialog
        alwaysOnTop={runtime.runtimeConfig.alwaysOnTop}
        autoHideInput={runtime.runtimeConfig.autoHideInput}
        autoHideTopTools={runtime.runtimeConfig.autoHideTopTools}
        configThemeColor={runtime.runtimeConfig.configThemeColor}
        configUseMainThemeColor={runtime.runtimeConfig.configUseMainThemeColor}
        dialogFill={runtime.runtimeConfig.dialogFill}
        dialogText={runtime.runtimeConfig.dialogText}
        dialogOpacity={runtime.runtimeConfig.dialogOpacity}
        dialogScale={runtime.runtimeConfig.dialogScale}
        dialogWidthPct={runtime.runtimeConfig.dialogWidthPct}
        effectiveDialogText={runtime.effectiveDialogText}
        effectiveNameText={runtime.effectiveNameText}
        immersiveMode={runtime.runtimeConfig.immersiveMode}
        mainThemeColor={runtime.mainThemeColor}
        miniInputShortcut={runtime.runtimeConfig.miniInputShortcut}
        nameText={runtime.runtimeConfig.nameText}
        onClose={() => modals.setToolbarConfigOpen(false)}
        onCommand={commands.sendCommand}
        onAlwaysOnTopChange={runtime.updateAlwaysOnTop}
        onAutoHideInputChange={runtime.updateAutoHideInput}
        onAutoHideTopToolsChange={runtime.updateAutoHideTopTools}
        onConfigThemeColorChange={runtime.updateConfigThemeColor}
        onConfigUseMainThemeColorChange={runtime.updateConfigUseMainThemeColor}
        onDialogFillChange={runtime.updateDialogFill}
        onDialogOpacityChange={runtime.updateDialogOpacity}
        onDialogScaleChange={runtime.updateDialogScale}
        onDialogWidthPctChange={runtime.updateDialogWidthPct}
        onImmersiveModeChange={runtime.updateImmersiveMode}
        onMiniInputShortcutChange={runtime.updateMiniInputShortcut}
        onResetThemeAppearance={runtime.resetThemeAppearance}
        onOpenPluginPage={pluginOverlay.openPluginPage}
        onSpriteOffsetXChange={runtime.updateSpriteOffsetX}
        onSpriteOffsetYChange={runtime.updateSpriteOffsetY}
        onSpriteScaleChange={runtime.updateSpriteScale}
        onSpriteFramingChange={runtime.updateSpriteFraming}
        onTextSpeedChange={runtime.updateTextSpeed}
        onTextStyleChange={runtime.updateTextStyle}
        onTurnOptionsChange={interaction.updateTurnOptions}
        onWindowScaleChange={runtime.updateWindowScale}
        open={modals.toolbarConfigOpen}
        spriteOffsetX={runtime.runtimeConfig.spriteOffsetX}
        spriteOffsetY={runtime.runtimeConfig.spriteOffsetY}
        spriteScales={runtime.runtimeConfig.spriteScales}
        spriteFramings={runtime.runtimeConfig.spriteFramings}
        sprites={stage.stageSprites}
        textSpeed={runtime.typewriterCps}
        turnOptions={state.turnOptions}
        voiceLanguage={viewModel.voiceLanguage || "ja"}
        windowControlsAvailable={desktop.standaloneDesktopWindow}
        windowScale={runtime.runtimeConfig.windowScale}
      />
    </>
  );
}
