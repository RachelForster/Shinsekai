import { useI18n } from "../../shared/i18n";
import { SegmentedTabs } from "../../shared/ui/SegmentedTabs";
import { lazy, Suspense, useState } from "react";
import { useSearchParams } from "react-router-dom";
import "./TemplateWorkspacePage.css";
import { ConversationLibrary } from "./ConversationLibrary";
import { ConversationTypeBadge } from "../../entities/chat/ConversationTypeBadge";

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
  const conversationId = params.get("conversation") || undefined;
  const tab = params.get("tab") === "new" || (!params.has("tab") && params.has("mode")) ? "new" : "recent";
  const [visited, setVisited] = useState(() => new Set(tab === "new" ? [mode] : []));
  const selectTab = (next: "new" | "recent") => {
    if (next === "new") setVisited((previous) => new Set([...previous, mode]));
    setParams((previous) => {
      previous.set("tab", next);
      return previous;
    });
  };
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
        ariaLabel={t("conversation.workspace")}
        idPrefix="conversation-view"
        className="template-workspace__tabs"
        value={tab}
        onChange={selectTab}
        items={[
          { id: "recent", label: t("conversation.recent") },
          { id: "new", label: t(conversationId ? "conversation.settings" : "conversation.new") },
        ]}
      />
      <div
        role="tabpanel"
        id="conversation-view-panel-recent"
        aria-labelledby="conversation-view-recent"
        hidden={tab !== "recent"}
      >
        {tab === "recent" && (
          <ConversationLibrary
            onCreate={() => {
              setVisited((previous) => new Set([...previous, "normal"]));
              setParams({ tab: "new", mode: "normal" });
            }}
            onEdit={(id, kind = "normal") => {
              setVisited((previous) => new Set([...previous, "normal"]));
              setParams({ tab: "new", mode: "normal", conversation: id, kind });
            }}
          />
        )}
      </div>
      <div
        role="tabpanel"
        id="conversation-view-panel-new"
        aria-labelledby="conversation-view-new"
        hidden={tab !== "new"}
      >
        {!conversationId && (
          <SegmentedTabs
            ariaLabel={t("template.workspace.label")}
            className="template-workspace__tabs"
            idPrefix="mode"
            items={modes.map((item) => ({ ...item, label: t(item.label) }))}
            value={mode}
            onChange={select}
          />
        )}
        {conversationId && <p className="section__description">{t("conversation.settingsHint")}</p>}
        <div className="template-workspace__type">
          <ConversationTypeBadge kind={conversationId ? (params.get("kind") === "story" ? "story" : "normal") : mode} />
        </div>
        {modes.map((item) => (
          <div
            key={item.id}
            id={`mode-panel-${item.id}`}
            role={conversationId ? undefined : "tabpanel"}
            aria-labelledby={conversationId ? undefined : `mode-${item.id}`}
            hidden={mode !== item.id}
          >
            {(visited.has(item.id) || (tab === "new" && mode === item.id)) && (
              <Suspense fallback={<p role="status">{t("common.loading")}</p>}>
                {item.id === "normal" ? (
                  <NormalMode
                    key={conversationId || "new"}
                    createOnly={!conversationId}
                    conversationId={conversationId}
                  />
                ) : (
                  <StoryMode />
                )}
              </Suspense>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
