import { useI18n } from "../../../shared/i18n";
import { layerClassName } from "../chatStageUtils";
import type { ChatStagePageController } from "../controllers/useChatStagePageController";
import { ReplayControls } from "../replay/ReplayControls";
import { runtimeSpriteFraming } from "../runtimeConfig";
import { playerPortraitForDialog } from "../state/text";
import { DialogStageControls } from "./DialogStageControls";
import { InputLayer } from "./InputLayer";
import { MiniAvatarStage } from "./MiniAvatarStage";
import { DialogLayer, OptionsLayer, ToolConfirmationLayer } from "./StageLayers";

export interface ChatStageDialogAreaProps {
  controller: ChatStagePageController;
}

export function ChatStageDialogArea({ controller }: ChatStageDialogAreaProps) {
  const { t } = useI18n();
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

  const dialogToolbar = historyReplay.activeReplay ? (
    <ReplayControls replay={historyReplay.activeReplay} progress={state.replay} onExit={historyReplay.exitReplay} />
  ) : (
    <DialogStageControls
      onEditConversation={() => modals.setConversationEditorOpen(true)}
      asrEnabled={viewModel.asrEnabled}
      auto={runtime.runtimeConfig.auto}
      autoOutfitSwitch={state.autoOutfitSwitch ?? true}
      bgmVolume={runtime.runtimeConfig.bgmVolume}
      effectVolume={runtime.runtimeConfig.effectVolume}
      closeLabel={t(desktop.standaloneDesktopWindow ? "desktop.titlebar.close" : "chat.toolbar.close")}
      configOpen={modals.toolbarConfigOpen}
      hidden={!stage.dialogSurfaceVisible}
      hideCloseButton={desktop.standaloneDesktopWindow}
      longPressTalk={runtime.runtimeConfig.longPressTalk}
      locked={modals.dialogControlsLocked}
      memoryMode={state.memoryMode}
      onAutoChange={runtime.setAuto}
      onBgmVolumeChange={runtime.updateBgmVolume}
      onEffectVolumeChange={runtime.updateEffectVolume}
      onCancelBatch={() => void commands.sendCommand({ type: "cancel-input-batch" })}
      onCloseSurface={desktop.closeSurface}
      onCommand={commands.sendCommand}
      onConfigOpenChange={modals.setToolbarConfigOpen}
      onFlushBatch={() => void commands.sendCommand({ type: "flush-input-batch" })}
      onLongPressTalkChange={runtime.updateLongPressTalk}
      onLockedChange={modals.setDialogControlsLocked}
      onOpenHistory={historyReplay.openHistoryDialog}
      onOpenPluginPage={pluginOverlay.openPluginPage}
      onOpenScreenSettings={() => screenShare.setScreenSettingsOpen(true)}
      onToggleScreenShare={
        stage.remoteMobileAccess || stage.standalone ? undefined : screenShare.handleToggleScreenShare
      }
      onTurnOptionsChange={interaction.updateTurnOptions}
      outfitCatalog={state.outfitCatalog}
      outfits={state.outfits}
      screenShareStarting={screenShare.screenShareStarting || screenShare.screenSharePreflightOpen}
      screenSharing={screenShare.screenSharing}
      showAsrControl={!viewModel.layers.input && !stage.standalone}
      turnOptions={state.turnOptions}
      turnState={state.turnState}
    />
  );

  return (
    <>
      <div
        aria-hidden={!stage.dialogSurfaceVisible || stage.miniAvatarActive}
        className={layerClassName("dialog-stack", !stage.dialogSurfaceVisible || stage.miniAvatarActive)}
        hidden={!stage.dialogSurfaceVisible || stage.miniAvatarActive}
      >
        {stage.miniAvatarActive ? null : viewModel.layers.options ? (
          <>
            {viewModel.toolConfirmation ? (
              <ToolConfirmationLayer
                confirmation={viewModel.toolConfirmation}
                onResolve={interaction.resolveToolConfirmation}
              />
            ) : (
              <OptionsLayer
                hidden={false}
                onSelect={interaction.submitOption}
                options={viewModel.options}
                readOnly={historyReplay.replaying}
                selectedIndex={state.replaySelectedIndex}
              />
            )}
            {!runtime.dialogToolbarDetached && !historyReplay.activeReplay ? (
              <div className="dialog-layer__toolbar">{dialogToolbar}</div>
            ) : null}
          </>
        ) : (
          <DialogLayer
            readOnly={historyReplay.replaying}
            canAdvance={viewModel.layers.dialog && !interaction.typingDialog && interaction.dialogTotalCharacters > 0}
            characterName={viewModel.dialogCharacterName}
            playerPortrait={playerPortraitForDialog(
              state.playerPortrait,
              viewModel.dialogCharacterName,
              viewModel.dialogText,
            )}
            hidden={!viewModel.layers.dialog || stage.miniAvatarActive}
            htmlNodes={interaction.displayedDialog.nodes}
            onAdvance={interaction.advanceDialog}
            onOpenPluginPage={pluginOverlay.openPluginPage}
            onSkip={interaction.typingDialog ? interaction.advanceDialog : undefined}
            text={interaction.typingDialog ? interaction.displayedDialog.text : viewModel.dialogText}
            textDirection={runtime.dialogTextDirection}
            toolbar={runtime.dialogToolbarDetached || historyReplay.activeReplay ? undefined : dialogToolbar}
            typing={interaction.typingDialog}
          />
        )}
      </div>
      {!stage.miniAvatarActive && (runtime.dialogToolbarDetached || historyReplay.activeReplay) ? (
        <div
          aria-hidden={!stage.dialogSurfaceVisible}
          className={layerClassName("dialog-toolbar-layer", !stage.dialogSurfaceVisible)}
          data-chat-stage-hitbox="true"
          data-locked={modals.dialogControlsLocked ? "true" : "false"}
          data-placement={historyReplay.activeReplay ? "input" : runtime.dialogToolbarPlacement}
          data-reveal={runtime.dialogToolbarReveal}
          hidden={!stage.dialogSurfaceVisible}
          ref={stage.dialogToolbarLayerRef}
        >
          {dialogToolbar}
        </div>
      ) : null}
      <InputLayer
        asrEnabled={viewModel.asrEnabled}
        asrLoading={viewModel.asrLoading}
        asrRunning={viewModel.asrRunning}
        attachments={viewModel.inputAttachments}
        autoHide={
          !historyReplay.replaying && runtime.runtimeConfig.immersiveMode && runtime.runtimeConfig.autoHideInput
        }
        batchEnabled={state.turnOptions.batchEnabled}
        disabled={Boolean(historyReplay.activeReplay) || viewModel.inputDisabled}
        locked={historyReplay.replaying}
        hidden={stage.miniAvatarActive || (!viewModel.layers.input && !historyReplay.replaying)}
        inputLayout={runtime.inputLayout}
        onChange={interaction.setDraft}
        onCommand={commands.sendCommand}
        onDropFiles={interaction.handleDropFiles}
        onFlushBatch={() => commands.sendCommand({ type: "flush-input-batch" })}
        onInputActivity={interaction.updateInputActivity}
        onPickAttachments={interaction.pickAttachments}
        onRemoveAttachment={interaction.removeAttachment}
        onSubmit={interaction.submit}
        previousMessages={interaction.recentInputs}
        replayProgress={state.replay}
        submitDisabled={interaction.attachmentUploadPending}
        value={viewModel.inputDraft}
      />
      {stage.miniAvatarActive ? (
        <MiniAvatarStage
          asrEnabled={viewModel.asrEnabled}
          asrLoading={viewModel.asrLoading}
          asrRunning={viewModel.asrRunning}
          attachments={viewModel.inputAttachments}
          autoPlay={runtime.runtimeConfig.auto}
          batchEnabled={state.turnOptions.batchEnabled}
          busyText={viewModel.busyText}
          canAdvance={
            (viewModel.status === "speaking" ||
              viewModel.status === "streaming" ||
              Boolean(viewModel.story) ||
              viewModel.behavior?.stagePolicy?.playbackEndAction === "auto_advance") &&
            viewModel.layers.dialog &&
            !interaction.typingDialog &&
            interaction.dialogTotalCharacters > 0
          }
          dialogCharacterName={viewModel.dialogCharacterName}
          dialogText={interaction.typingDialog ? interaction.displayedDialog.text : viewModel.dialogText}
          dialogVisible={viewModel.layers.dialog}
          dockSide={desktop.miniDockSide}
          inputDisabled={viewModel.inputDisabled}
          inputValue={viewModel.inputDraft}
          locked={historyReplay.replaying}
          longPressTalk={runtime.runtimeConfig.longPressTalk}
          miniInputShortcut={runtime.runtimeConfig.miniInputShortcut}
          notificationText={viewModel.notificationText}
          notificationVisible={viewModel.layers.notification}
          onAdvance={interaction.advanceDialog}
          onAutoPlayChange={runtime.setAuto}
          onChangeInput={interaction.setDraft}
          onCommand={commands.sendCommand}
          onDesktopDragEnd={desktop.syncDesktopMiniDockSide}
          onDropFiles={interaction.handleDropFiles}
          onExitMiniMode={desktop.exitMiniAvatarMode}
          onFlushBatch={() => commands.sendCommand({ type: "flush-input-batch" })}
          onInputActivity={interaction.updateInputActivity}
          onInputPinnedChange={desktop.setMiniInputPinned}
          onLongPressTalkChange={runtime.updateLongPressTalk}
          onPickAttachments={interaction.pickAttachments}
          onRemoveAttachment={interaction.removeAttachment}
          onResolveToolConfirmation={interaction.resolveToolConfirmation}
          onSelectOption={interaction.submitOption}
          onSubmit={interaction.submit}
          onToggleScreenShare={stage.remoteMobileAccess ? undefined : screenShare.handleToggleScreenShare}
          options={viewModel.options}
          optionsVisible={viewModel.layers.options}
          playerPortrait={playerPortraitForDialog(
            state.playerPortrait,
            viewModel.dialogCharacterName,
            viewModel.dialogText,
          )}
          previousMessages={interaction.recentInputs}
          runtimeFramingForSprite={(sprite, index) => runtimeSpriteFraming(runtime.runtimeConfig, sprite, index)}
          screenShareStarting={screenShare.screenShareStarting || screenShare.screenSharePreflightOpen}
          screenSharing={screenShare.screenSharing}
          shortcutDisabled={stage.modalOpen}
          spriteReaction={viewModel.spriteReaction}
          sprites={stage.stageSprites}
          standaloneDesktopWindow={desktop.standaloneDesktopWindow}
          status={viewModel.status}
          submitDisabled={interaction.attachmentUploadPending}
          thinkingCharacterName={viewModel.thinkingCharacterName}
          toolConfirmation={viewModel.toolConfirmation}
          typing={interaction.typingDialog}
          userDisplayName={viewModel.userDisplayName}
        />
      ) : null}
    </>
  );
}
