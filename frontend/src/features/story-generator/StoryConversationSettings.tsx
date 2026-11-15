import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { conversationsQueryKey, listConversations, updateConversationSettings } from "../../entities/chat/repository";
import { listStories, storyLibraryQueryKey } from "../../entities/story/repository";
import { useI18n } from "../../shared/i18n";
import { Button, Select, Switch } from "../../shared/ui";
import type { ConversationSummary, MemoryMode } from "../../shared/platform/types";
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
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [localMemoryMode, setLocalMemoryMode] = useState<MemoryMode | null>(null);
  const [localAutoOutfitSwitch, setLocalAutoOutfitSwitch] = useState<boolean | null>(null);
  const query = useQuery({
    queryKey: conversationsQueryKey,
    queryFn: listConversations,
    enabled: !conversation,
    staleTime: 0,
  });
  const current = conversation ?? query.data?.find((item) => item.id === conversationId);
  const stories = useQuery({
    queryKey: storyLibraryQueryKey,
    queryFn: listStories,
    enabled: current?.kind === "story" && Boolean(current.storyPath),
    staleTime: 0,
  });
  const settingsMutation = useMutation({
    mutationFn: (patch: { autoOutfitSwitch?: boolean; memoryMode?: MemoryMode }) => {
      if (!current) {
        throw new Error(t("conversation.unavailable"));
      }
      return updateConversationSettings(current.id, patch);
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: conversationsQueryKey });
    },
  });

  const effectiveMemoryMode = localMemoryMode ?? current?.memoryMode ?? "isolated";
  const effectiveAutoOutfitSwitch = localAutoOutfitSwitch ?? current?.autoOutfitSwitch ?? true;
  const canEdit = stories.data?.some((story) => story.storyPath === current?.storyPath && story.canEditGraph === true);

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
            <div className="form-grid form-grid--two">
              <label className="field-row">
                <span className="field-row__label">{t("chat.memoryMode.label")}</span>
                <span className="field-row__control">
                  <Select
                    aria-label={t("chat.memoryMode.label")}
                    disabled={settingsMutation.isPending}
                    onChange={(event) => {
                      const nextMode = event.target.value as MemoryMode;
                      setLocalMemoryMode(nextMode);
                      settingsMutation.mutate({ memoryMode: nextMode });
                    }}
                    value={effectiveMemoryMode}
                  >
                    <option value="isolated">{t("chat.memoryMode.isolated")}</option>
                    <option value="shared">{t("chat.memoryMode.shared")}</option>
                    <option value="inherit_readonly">{t("chat.memoryMode.inheritReadonly")}</option>
                  </Select>
                </span>
              </label>
              <div className="field-row">
                <label className="field-row__label" htmlFor="story-auto-outfit-switch">
                  {t("launch.autoOutfitSwitch")}
                </label>
                <span className="field-row__control">
                  <Switch
                    aria-label={t("launch.autoOutfitSwitch")}
                    checked={effectiveAutoOutfitSwitch}
                    disabled={settingsMutation.isPending}
                    id="story-auto-outfit-switch"
                    onChange={(event) => {
                      const enabled = event.target.checked;
                      setLocalAutoOutfitSwitch(enabled);
                      settingsMutation.mutate({ autoOutfitSwitch: enabled });
                    }}
                  />
                </span>
              </div>
            </div>
            {!conversation && (
              <StoryLaunchButton
                storyPath={current.storyPath}
                historyPath={current.historyPath}
                conversationId={current.hasSettings ? current.id : undefined}
                label={t("story.library.continue")}
              />
            )}
            {editing && canEdit ? (
              <StoryEditor
                key={current.storyPath}
                storyPath={current.storyPath}
                onClose={() => setEditing(false)}
                onPendingChange={onPendingChange}
              />
            ) : canEdit ? (
              <Button onClick={() => setEditing(true)}>{t("story.editor.openFromSettings")}</Button>
            ) : (
              <p className="section__description">
                {t(stories.isPending ? "common.loading" : "story.editor.unsupported")}
              </p>
            )}
          </>
        ) : (
          (conversation || query.isSuccess) && <p role="alert">{t("conversation.missingStory")}</p>
        )}
      </section>
    </StoryFeatureGate>
  );
}
