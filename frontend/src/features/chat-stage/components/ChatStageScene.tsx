import { ChatSoundPlayer } from "../audio/ChatSoundPlayer";
import type { ChatStagePageController } from "../controllers/useChatStagePageController";
import { runtimeSpriteFraming, runtimeSpriteScale } from "../runtimeConfig";
import {
  CgLayer,
  AmbientLayer,
  BackgroundLayer,
  BusyLayer,
  EffectImageLayer,
  NotificationLayer,
  SpriteLayer,
  StatLayer,
  StandaloneDesktopResizeHandles,
  TokenUsageLayer,
} from "./StageLayers";
import { ReactionBubble } from "./ReactionBubble";
import { StoryDebugPanel } from "./StoryDebugPanel";
import { TopStageTools } from "./TopStageTools";

export interface ChatStageSceneProps {
  controller: ChatStagePageController;
}

export function ChatStageScene({ controller }: ChatStageSceneProps) {
  const { desktop, historyReplay, interaction, modals, pluginOverlay, runtime, stage, state, viewModel } = controller;

  return (
    <>
      <StandaloneDesktopResizeHandles hidden={!desktop.standaloneDesktopWindow || stage.miniAvatarActive} />
      <TopStageTools
        autoHide={
          !historyReplay.activeReplay && runtime.runtimeConfig.immersiveMode && runtime.runtimeConfig.autoHideTopTools
        }
        hidden={!viewModel.layers.toolbar || stage.miniAvatarActive}
        miniAvatarDisabled={historyReplay.replaying}
        onCloseDesktopWindow={desktop.closeSurface}
        onEnterMiniAvatar={stage.remoteMobileAccess ? undefined : desktop.enterMiniAvatarMode}
        onOpenPluginPage={pluginOverlay.openPluginPage}
        onOpenRuntimeMode={!desktop.desktopApp ? () => modals.setRuntimeModeOpen(true) : undefined}
        onOpenWorkspace={!desktop.desktopApp ? stage.openWorkspace : undefined}
        onThemePickerOpenChange={modals.setThemePickerOpen}
        onTokenUsageOpenChange={modals.setTokenUsageOpen}
        standaloneDesktopWindow={desktop.standaloneDesktopWindow}
        status={historyReplay.activeReplay ? "replaying" : viewModel.statusText}
        themePickerOpen={modals.themePickerOpen}
        tokenUsageAvailable={Boolean(viewModel.tokenUsageText)}
        tokenUsageOpen={modals.tokenUsageOpen}
        transportMode={viewModel.transportMode}
        transportState={viewModel.transportState}
      />
      <BackgroundLayer
        hidden={!viewModel.layers.background || stage.miniAvatarActive}
        onDragStart={
          desktop.standaloneDesktopWindow && !stage.transparentBackground ? desktop.handleWindowDrag : undefined
        }
        path={viewModel.backgroundPath}
        transition={viewModel.backgroundTransition}
        transparent={stage.transparentBackground}
      />
      <ChatSoundPlayer
        ref={historyReplay.soundPlayerRef}
        voicePaused={Boolean(state.replay?.paused)}
        key={state.sessionId}
        ambientEffects={state.ambientEffects}
        bgmPath={viewModel.bgmPath}
        bgmVolume={runtime.runtimeConfig.bgmVolume}
        effectVolume={runtime.runtimeConfig.effectVolume}
        commands={state.audioCommands}
        onPlaybackSignal={interaction.handlePlaybackSignal}
      />
      <CgLayer
        hidden={!viewModel.layers.cg || stage.miniAvatarActive}
        onExit={historyReplay.exitCg}
        onSave={() => void historyReplay.saveCg()}
        path={viewModel.cgPath}
        saving={historyReplay.savingCg}
        standaloneDesktopWindow={desktop.standaloneDesktopWindow}
      />
      {!stage.miniAvatarActive ? (
        <AmbientLayer effects={state.ambientEffects ?? []} hidden={false} layer="back" />
      ) : null}
      {!stage.miniAvatarActive ? <EffectImageLayer effect={state.effectImage} /> : null}
      <SpriteLayer
        hidden={!viewModel.layers.sprites || stage.miniAvatarActive}
        onDragStart={desktop.standaloneDesktopWindow ? desktop.handleWindowDrag : undefined}
        runtimeScaleForSprite={(sprite, index) => runtimeSpriteScale(runtime.runtimeConfig, sprite, index)}
        runtimeFramingForSprite={(sprite, index) => runtimeSpriteFraming(runtime.runtimeConfig, sprite, index)}
        speaker={viewModel.dialogCharacterName}
        responding={viewModel.status === "speaking" || viewModel.status === "streaming" || interaction.typingDialog}
        spriteMotions={viewModel.spriteMotions}
        thinkingCharacterName={viewModel.thinkingCharacterName}
        sprites={stage.stageSprites}
      />
      {!stage.miniAvatarActive ? (
        <AmbientLayer effects={state.ambientEffects ?? []} hidden={false} layer="front" />
      ) : null}
      <ReactionBubble
        hidden={
          stage.miniAvatarActive ||
          historyReplay.replaying ||
          viewModel.status === "streaming" ||
          viewModel.status === "speaking" ||
          interaction.typingDialog
        }
        reaction={viewModel.spriteReaction}
        sprites={stage.stageSprites}
      />
      {!stage.miniAvatarActive ? <StatLayer stats={viewModel.stats} /> : null}
      {!stage.miniAvatarActive ? <StoryDebugPanel story={viewModel.story} /> : null}
      <TokenUsageLayer hidden={!stage.tokenUsageVisible || stage.miniAvatarActive} text={viewModel.tokenUsageText} />
      <BusyLayer hidden={!viewModel.layers.busy || stage.miniAvatarActive} text={viewModel.busyText} />
      <NotificationLayer
        hidden={!viewModel.layers.notification || stage.miniAvatarActive}
        spritesVisible={viewModel.layers.sprites && stage.stageSprites.length > 0}
        text={viewModel.notificationText}
      />
    </>
  );
}
