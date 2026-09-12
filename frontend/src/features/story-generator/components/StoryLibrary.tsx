import { useI18n } from "../../../shared/i18n";
import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import { useQuery } from "@tanstack/react-query";
import { listStories, storyLibraryQueryKey } from "../../../entities/story/repository";
import { Button } from "../../../shared/ui";
import { StoryLaunchButton } from "./StoryLaunchButton";

export function StoryLibrary({ onCreate }: { onCreate: () => void }) {
  const { t, language } = useI18n();
  const listFormatter = new Intl.ListFormat(language.replace("_", "-"), { style: "short", type: "unit" });
  const stories = useQuery({ queryKey: storyLibraryQueryKey, queryFn: listStories, staleTime: 0 });
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
            <p>
              {story.historyPath
                ? t("story.library.progress", { node: story.currentNodeTitle || t("story.library.saved") })
                : t("story.library.unplayed")}
            </p>
            <StoryLaunchButton
              key={`${story.storyPath}-${story.historyPath}`}
              storyPath={story.storyPath}
              historyPath={story.historyPath}
              label={story.historyPath ? t("story.library.continue") : t("story.library.start")}
            />
          </article>
        ))}
      </div>
    </section>
  );
}
