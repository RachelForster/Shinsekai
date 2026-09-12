import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { chatQueryKey, getChatRuntimeStatus, getChatSnapshot, launchChat } from "../../../entities/chat/repository";
import { prepareStoryLaunch, startStorySession, storyLibraryQueryKey } from "../../../entities/story/repository";
import { showChatSurface } from "../../../shared/desktop/chatWindow";
import { ChatInitializationDialog } from "../../chat-startup/ChatInitializationDialog";
import { useChatInitialization } from "../../chat-startup/useChatInitialization";

const pendingAttachmentKey = "story.pending-attachment.v1";

function pendingAttachment() {
  try {
    return JSON.parse(localStorage.getItem(pendingAttachmentKey) || "null") as {
      storyPath: string;
      historyPath: string;
      sessionId: string;
    } | null;
  } catch {
    return null;
  }
}

export function StoryLaunchButton({
  storyPath,
  historyPath = "",
  label,
  disabled = false,
}: {
  storyPath: string;
  historyPath?: string;
  label?: string;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const client = useQueryClient();
  const init = useChatInitialization();
  const [error, setError] = useState("");
  const launch = async () => {
    if (!storyPath || init.initializationPending) return;
    setError("");
    try {
      const snapshot = await init.runChatInitialization(async (options) => {
        const status = await getChatRuntimeStatus();
        let launched;
        if (status.state !== "idle") {
          const pending = pendingAttachment();
          if (!pending || pending.storyPath !== storyPath || pending.historyPath !== historyPath) {
            throw new Error(t("story.launch.busy"));
          }
          const current = await getChatSnapshot();
          if (status.state === "closing" || !pending.sessionId || current.sessionId !== pending.sessionId) {
            throw new Error(t("story.launch.changed"));
          }
          launched = current;
        } else {
          launched = await launchChat(await prepareStoryLaunch(storyPath, historyPath), options);
          localStorage.setItem(
            pendingAttachmentKey,
            JSON.stringify({ storyPath, historyPath, sessionId: launched.sessionId }),
          );
        }
        const story = await startStorySession(storyPath);
        return { ...launched, ...story };
      });
      client.setQueryData(chatQueryKey, snapshot);
      void client.invalidateQueries({ queryKey: storyLibraryQueryKey });
      await showChatSurface({ navigate, snapshot });
      localStorage.removeItem(pendingAttachmentKey);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  return (
    <>
      <Button
        variant="primary"
        type="button"
        disabled={disabled || !storyPath || init.initializationPending}
        onClick={() => void launch()}
      >
        {init.initializationPending ? t("story.launch.starting") : (label ?? t("story.launch.action"))}
      </Button>
      {error && (
        <p className="story-generator-error" role="alert">
          {error}
        </p>
      )}
      <ChatInitializationDialog
        error={init.initializationError}
        onClose={init.closeInitialization}
        open={init.initializationOpen}
        pending={init.initializationPending}
        task={init.initializationTask}
      />
    </>
  );
}
