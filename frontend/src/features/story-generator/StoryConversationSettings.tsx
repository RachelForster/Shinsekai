import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { conversationsQueryKey, listConversations } from "../../entities/chat/repository";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";
import type { ConversationSummary } from "../../shared/platform/types";
import { StoryEditor } from "./editor/StoryEditor";
import { StoryFeatureGate } from "./components/StoryFeatureGate";
import { StoryLaunchButton } from "./components/StoryLaunchButton";

export function StoryConversationSettings({
  conversationId,
  conversation,
  onPendingChange,
}: {
  conversationId?: string;
  conversation?: ConversationSummary;
  onPendingChange?: (pending: boolean) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const query = useQuery({
    queryKey: conversationsQueryKey,
    queryFn: listConversations,
    enabled: !conversation,
    staleTime: 0,
  });
  const current = conversation ?? query.data?.find((item) => item.id === conversationId);
  return (
    <StoryFeatureGate>
      <section className="section">
        <h2 className="section__title">{t("story.editor.settings")}</h2>
        <p className="section__description">{t("story.editor.settingsHint")}</p>
        {!conversation && query.isPending && <p role="status">{t("common.loading")}</p>}
        {!conversation && query.isError && (
          <>
            <p role="alert">{query.error.message}</p>
            <Button onClick={() => void query.refetch()}>{t("common.refresh")}</Button>
          </>
        )}
        {current?.kind === "story" && current.storyPath ? (
          <>
            {!conversation && (
              <StoryLaunchButton
                storyPath={current.storyPath}
                historyPath={current.historyPath}
                conversationId={current.hasSettings ? current.id : undefined}
                label={t("story.library.continue")}
              />
            )}
            {editing ? (
              <StoryEditor
                key={current.storyPath}
                storyPath={current.storyPath}
                onClose={() => setEditing(false)}
                onPendingChange={onPendingChange}
              />
            ) : (
              <Button onClick={() => setEditing(true)}>{t("story.editor.openFromSettings")}</Button>
            )}
          </>
        ) : (
          (conversation || query.isSuccess) && <p role="alert">{t("conversation.missingStory")}</p>
        )}
      </section>
    </StoryFeatureGate>
  );
}
