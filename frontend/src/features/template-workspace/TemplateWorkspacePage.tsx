import { lazy, Suspense, useState } from "react";
import { ArrowLeft, BookOpen, MessageCircle } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui/Button";
import { Dialog } from "../../shared/ui/Dialog";
import { TextInput } from "../../shared/ui/FormControls";
import { ConversationLibrary } from "./ConversationLibrary";
import { ConversationTypeBadge } from "../../entities/chat/ConversationTypeBadge";
import "./TemplateWorkspacePage.css";

const NormalMode = lazy(() =>
  import("../template-editor/TemplateEditorPage").then(({ TemplateEditorPage }) => ({ default: TemplateEditorPage })),
);
const StoryMode = lazy(() =>
  import("../story-generator/StoryGeneratorPage").then(({ StoryGeneratorPage }) => ({ default: StoryGeneratorPage })),
);

export function TemplateWorkspacePage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const conversationId = params.get("conversation") || undefined;
  const configuring =
    params.get("tab") === "new" || Boolean(conversationId) || (!params.has("tab") && params.has("mode"));
  const mode = params.get("mode") === "story" ? "story" : "normal";
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState<"normal" | "story">("normal");
  const [draftTitle, setDraftTitle] = useState("");
  const [title, setTitle] = useState("");
  const [draftKey, setDraftKey] = useState(0);
  const back = () => setParams({ tab: "recent" });
  return (
    <div className="template-workspace">
      {configuring ? (
        <>
          <header className="conversation-setup__header">
            <Button variant="ghost" icon={<ArrowLeft aria-hidden className="button__icon" />} onClick={back}>
              {t("conversation.workspace")}
            </Button>
            <ConversationTypeBadge
              kind={conversationId ? (params.get("kind") === "story" ? "story" : "normal") : mode}
            />
          </header>
          {conversationId ? (
            <h1 className="conversation-setup__title">{t("conversation.settings")}</h1>
          ) : (
            <label className="conversation-setup__name">
              <span>{t("conversation.title")}</span>
              <TextInput value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
            </label>
          )}
          <Suspense fallback={<p role="status">{t("common.loading")}</p>}>
            {conversationId || mode === "normal" ? (
              <NormalMode
                key={conversationId || draftKey}
                createOnly={!conversationId}
                conversationId={conversationId}
                conversationTitle={title}
              />
            ) : (
              <StoryMode key={draftKey} conversationTitle={title} />
            )}
          </Suspense>
        </>
      ) : (
        <ConversationLibrary
          onCreate={() => {
            setDraftTitle("");
            setKind("normal");
            setCreating(true);
          }}
          onEdit={(id, selectedKind = "normal") =>
            setParams({ tab: "new", mode: "normal", conversation: id, kind: selectedKind })
          }
        />
      )}
      <Dialog
        open={creating}
        title={t("conversation.new")}
        closeLabel={t("common.close")}
        onClose={() => setCreating(false)}
        className="conversation-create-dialog"
        footer={
          <>
            <Button onClick={() => setCreating(false)}>{t("common.cancel")}</Button>
            <Button
              variant="primary"
              disabled={!draftTitle.trim()}
              onClick={() => {
                setTitle(draftTitle.trim());
                setDraftKey((key) => key + 1);
                setParams({ tab: "new", mode: kind });
                setCreating(false);
              }}
            >
              {t("conversation.next")}
            </Button>
          </>
        }
      >
        <label className="conversation-setup__name">
          <span>{t("conversation.title")}</span>
          <TextInput value={draftTitle} maxLength={120} onChange={(event) => setDraftTitle(event.target.value)} />
        </label>
        <fieldset className="conversation-create__types">
          <legend>{t("conversation.chooseType")}</legend>
          {(["normal", "story"] as const).map((value) => {
            const Icon = value === "normal" ? MessageCircle : BookOpen;
            return (
              <label key={value} className={`conversation-create__type${kind === value ? " is-selected" : ""}`}>
                <input
                  type="radio"
                  name="conversation-kind"
                  value={value}
                  checked={kind === value}
                  onChange={() => setKind(value)}
                />
                <Icon aria-hidden />
                <span>
                  <strong>{t(`conversation.${value}`)}</strong>
                  <small>{t(`conversation.${value}Hint`)}</small>
                </span>
              </label>
            );
          })}
        </fieldset>
      </Dialog>
    </div>
  );
}
