import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  chatQueryKey,
  conversationsQueryKey,
  getChatRuntimeStatus,
  getChatSnapshot,
  launchChat,
  prepareConversation,
} from "../../../entities/chat/repository";
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
  conversationId,
  conversationTitle,
}: {
  storyPath: string;
  historyPath?: string;
  label?: string;
  disabled?: boolean;
  conversationId?: string;
  conversationTitle?: string;
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
          const payload = await prepareStoryLaunch(storyPath, historyPath);
          launched = await launchChat(
            conversationId
              ? await prepareConversation(conversationId)
              : { ...payload, conversationTitle: conversationTitle?.trim() },
            options,
          );
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
      void client.invalidateQueries({ queryKey: conversationsQueryKey });
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
        disabled={
          disabled ||
          !storyPath ||
          init.initializationPending ||
          (conversationTitle !== undefined && !conversationTitle.trim())
        }
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
