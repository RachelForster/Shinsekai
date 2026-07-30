import { useEffect, useRef, useState } from "react";
import { Volume2 } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { currentChatRendererId } from "../../../shared/platform/chatRenderer";
import { stageAssetUrl } from "../chatStageUtils";
import type { ChatAudioCommand } from "../state/types";
import { SoundPlayer, type VoicePlaybackSignal } from "./soundPlayer";

export function ChatSoundPlayer({
  bgmPath,
  bgmVolume,
  commands,
  onPlaybackSignal,
}: {
  bgmPath?: string;
  bgmVolume: number;
  commands: ChatAudioCommand[];
  onPlaybackSignal: (signal: VoicePlaybackSignal) => void;
}) {
  const playerRef = useRef<SoundPlayer | null>(null);
  const processedCommandIdsRef = useRef(new Set<string>());
  const [locked, setLocked] = useState(false);
  const { t } = useI18n();

  if (!playerRef.current && typeof Audio !== "undefined") {
    playerRef.current = new SoundPlayer();
  }

  useEffect(() => {
    const player = playerRef.current;
    if (!player) {
      return;
    }
    return player.subscribeLock(setLocked);
  }, []);

  useEffect(() => playerRef.current?.subscribeVoiceSignal(onPlaybackSignal), [onPlaybackSignal]);

  useEffect(() => {
    playerRef.current?.setBgm(stageAssetUrl(bgmPath), bgmVolume);
  }, [bgmPath, bgmVolume]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) {
      return;
    }
    for (const command of commands) {
      const commandId =
        command.kind === "voice-play"
          ? `${command.kind}:${command.playbackId}:${command.rendererId ?? ""}`
          : command.kind === "voice-stop"
            ? `${command.kind}:${command.playbackId}:${command.seq}`
            : "key" in command
              ? `${command.kind}:${command.key}:${command.seq}`
              : `${command.kind}:${command.seq}`;
      if (processedCommandIdsRef.current.has(commandId)) {
        continue;
      }
      processedCommandIdsRef.current.add(commandId);
      if (processedCommandIdsRef.current.size > 256) {
        const oldest = processedCommandIdsRef.current.values().next().value;
        if (oldest) {
          processedCommandIdsRef.current.delete(oldest);
        }
      }
      switch (command.kind) {
        case "voice-play":
          if (!command.rendererId || command.rendererId === currentChatRendererId()) {
            player.playVoice(command.playbackId, stageAssetUrl(command.url), command.volume);
          }
          break;
        case "voice-stop":
          player.stopVoice(command.playbackId);
          break;
        case "effect-play":
          player.playEffect(stageAssetUrl(command.url));
          break;
        case "effect-loop-start":
          player.startLoopEffect(command.key, stageAssetUrl(command.url));
          break;
        case "effect-loop-stop":
          player.stopLoopEffect(command.key);
          break;
        case "effect-loop-stop-all":
          player.stopAllLoopEffects();
          break;
        case "all-stop":
          player.stopAll();
          break;
      }
    }
  }, [commands]);

  useEffect(
    () => () => {
      playerRef.current?.dispose();
      playerRef.current = null;
    },
    [],
  );

  return (
    <>
      <span aria-hidden data-bgm-src={stageAssetUrl(bgmPath)} data-chat-stage-audio-player hidden />
      {locked ? (
        <aside className="chat-stage__audio-unlock" data-chat-stage-hitbox="true" role="status">
          <p>{t("chat.audio.unlockHint")}</p>
          <Button
            icon={<Volume2 aria-hidden className="button__icon" />}
            onClick={() => void playerRef.current?.unlock()}
            variant="primary"
          >
            {t("chat.audio.unlock")}
          </Button>
        </aside>
      ) : null}
    </>
  );
}
