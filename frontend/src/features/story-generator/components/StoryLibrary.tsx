import { useI18n } from "../../../shared/i18n";
import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteStory, listStories, storyLibraryQueryKey } from "../../../entities/story/repository";
import { chatQueryKey } from "../../../entities/chat/repository";
import type { StoryLibraryEntry } from "../../../shared/platform/types";
import { Button, Dialog } from "../../../shared/ui";
import { StoryLaunchButton } from "./StoryLaunchButton";
import { useState } from "react";
import { StoryEditor } from "../editor/StoryEditor";

export function StoryLibrary({ onCreate, conversationTitle }: { onCreate: () => void; conversationTitle?: string }) {
  const { t, language } = useI18n();
  const [editing, setEditing] = useState("");
  const [deleting, setDeleting] = useState<StoryLibraryEntry | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const listFormatter = new Intl.ListFormat(language.replace("_", "-"), { style: "short", type: "unit" });
  const stories = useQuery({ queryKey: storyLibraryQueryKey, queryFn: listStories, staleTime: 0 });
  const remove = async () => {
    if (!deleting || saving) return;
    setSaving(true);
    setError("");
    try {
      await deleteStory(deleting.storyPath);
      await Promise.all([
        client.invalidateQueries({ queryKey: storyLibraryQueryKey }),
        client.invalidateQueries({ queryKey: chatQueryKey }),
      ]);
      setDeleting(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };
  if (editing) return <StoryEditor key={editing} storyPath={editing} onClose={() => setEditing("")} />;
  return (
    <section className="section">
      <div className="story-library-header">
        <h2 className="section__title">{t("story.library")}</h2>
        <Button disabled={stories.isFetching} onClick={() => void stories.refetch()}>
          {t("common.refresh")}
        </Button>
      </div>
      {stories.isPending && <p role="status">{t("story.library.loading")}</p>}
      {stories.isError && (
        <p role="alert" className="story-generator-error">
          {stories.error.message}
        </p>
      )}
      {stories.isSuccess && !stories.data.length && (
        <div>
          <p className="section__description">{t("story.library.empty")}</p>
          <Button variant="primary" onClick={onCreate}>
            {t("story.create")}
          </Button>
        </div>
      )}
      <div className="story-library-grid">
        {stories.data?.map((story) => (
          <article className="story-library-card" key={story.storyPath}>
            <h3>{story.title}</h3>
            {story.version !== undefined && (
              <p className="section__description">{t("story.editor.version", { version: story.version })}</p>
            )}
            <p className="section__description">
              {listFormatter.format(story.characters) || t("story.library.characters")}
            </p>
            <p className="section__description">
              {t("story.library.background", {
                background:
                  listFormatter.format(
                    story.backgrounds.map((name) =>
                      name === TRANSPARENT_BACKGROUND_NAME ? t("template.transparentBackground") : name,
                    ),
                  ) || t("template.transparentBackground"),
              })}
            </p>
            <div className="story-library-card__actions">
              <StoryLaunchButton
                key={`${story.storyPath}-${story.historyPath}`}
                storyPath={story.storyPath}
                disabled={saving}
                conversationTitle={conversationTitle}
                label={t("conversation.createAndStart")}
              />
              {story.canEditGraph === true && (
                <Button disabled={saving} onClick={() => setEditing(story.storyPath)}>
                  {t("story.editor.edit")}
                </Button>
              )}
              <Button
                variant="danger"
                disabled={saving}
                onClick={() => {
                  setDeleting(story);
                  setError("");
                }}
              >
                {t("common.delete")}
              </Button>
            </div>
            {story.canEditGraph !== true && <p className="section__description">{t("story.editor.unsupported")}</p>}
          </article>
        ))}
      </div>
      <Dialog
        open={Boolean(deleting)}
        title={t("story.library.delete")}
        closeLabel={t("common.close")}
        dismissible={!saving}
        onClose={() => {
          if (!saving) setDeleting(null);
        }}
        footer={
          <>
            <Button disabled={saving} onClick={() => setDeleting(null)}>
              {t("common.cancel")}
            </Button>
            <Button variant="danger" disabled={saving} onClick={() => void remove()}>
              {t("common.delete")}
            </Button>
          </>
        }
      >
        <p>{t("story.library.deleteConfirm", { title: deleting?.title ?? "", version: deleting?.version ?? "—" })}</p>
        {error && <p role="alert">{error}</p>}
      </Dialog>
    </section>
  );
}
