import { useI18n } from "../../shared/i18n";
import { SegmentedTabs } from "../../shared/ui/SegmentedTabs";
import { lazy, Suspense, useState } from "react";
import { useSearchParams } from "react-router-dom";
import "./TemplateWorkspacePage.css";

const NormalMode = lazy(() =>
  import("../template-editor/TemplateEditorPage").then(({ TemplateEditorPage }) => ({ default: TemplateEditorPage })),
);
const StoryMode = lazy(() =>
  import("../story-generator/StoryGeneratorPage").then(({ StoryGeneratorPage }) => ({ default: StoryGeneratorPage })),
);
const modes = [
  { id: "normal", label: "template.workspace.normal" },
  { id: "story", label: "template.workspace.story" },
] as const;

export function TemplateWorkspacePage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const mode = params.get("mode") === "story" ? "story" : "normal";
  const [visited, setVisited] = useState(() => new Set([mode]));
  const select = (next: typeof mode) => {
    setVisited((previous) => new Set([...previous, next]));
    setParams((previous) => {
      previous.set("mode", next);
      return previous;
    });
  };
  return (
    <div className="template-workspace">
      <SegmentedTabs
        ariaLabel={t("template.workspace.label")}
        className="template-workspace__tabs"
        idPrefix="mode"
        items={modes.map((item) => ({ ...item, label: t(item.label) }))}
        value={mode}
        onChange={select}
      />
      {modes.map((item) => (
        <div
          key={item.id}
          id={`mode-panel-${item.id}`}
          role="tabpanel"
          aria-labelledby={`mode-${item.id}`}
          hidden={mode !== item.id}
        >
          {(visited.has(item.id) || mode === item.id) && (
            <Suspense fallback={<p role="status">{t("common.loading")}</p>}>
              {item.id === "normal" ? <NormalMode /> : <StoryMode />}
            </Suspense>
          )}
        </div>
      ))}
    </div>
  );
}
