import { lazy, Suspense, useState } from "react";
import { ArrowLeft, BookOpen, MessageCircle, ScrollText } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui/Button";
import { Dialog } from "../../shared/ui/Dialog";
import { TextInput } from "../../shared/ui/FormControls";
import { SegmentedRadio } from "../../shared/ui/SegmentedRadio";
import { ConversationLibrary } from "./ConversationLibrary";
import { ConversationTypeBadge } from "./ConversationTypeBadge";
import { resolveConversationTitle } from "../../entities/chat/conversationTitle";
import { useChatInitialization } from "../chat-startup/useChatInitialization";
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { useMobileAccessLaunch } from "../mobile-access/useMobileAccessLaunch";
import "./ChatWorkspacePage.css";

const NormalMode = lazy(() =>
  import("../template-editor/TemplateEditorPage").then(({ TemplateEditorPage }) => ({ default: TemplateEditorPage })),
);
const StoryMode = lazy(() =>
  import("../story-generator/StoryGeneratorPage").then(({ StoryGeneratorPage }) => ({ default: StoryGeneratorPage })),
);
const StorySettings = lazy(() =>
  import("../story-generator/StoryConversationSettings").then(({ StoryConversationSettings }) => ({
    default: StoryConversationSettings,
  })),
);
const NovelMode = lazy(() =>
  import("../novel-theater/NovelTheaterWizardPage").then(({ NovelTheaterWizardPage }) => ({
    default: NovelTheaterWizardPage,
  })),
);
const NovelSettings = lazy(() =>
  import("../novel-theater/NovelConversationSettings").then(({ NovelConversationSettings }) => ({
    default: NovelConversationSettings,
  })),
);

export function ChatWorkspacePage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const initialization = useChatInitialization();
  const mobileAccess = useMobileAccessLaunch();
  const conversationId = params.get("conversation") || undefined;
  const configuring =
    params.get("tab") === "new" || Boolean(conversationId) || (!params.has("tab") && params.has("mode"));
  const modeParam = params.get("mode");
  const mode = modeParam === "story" ? "story" : modeParam === "novel" ? "novel" : "normal";
  const urlKind = params.get("kind");
  const activeKind: "normal" | "story" | "novel" = conversationId
    ? urlKind === "story"
      ? "story"
      : urlKind === "novel"
        ? "novel"
        : mode
    : mode;
  const isNormalEditor = configuring && activeKind === "normal";
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState<"normal" | "story" | "novel">("normal");
  const [draftTitle, setDraftTitle] = useState("");
  const [title, setTitle] = useState("");
  const [draftKey, setDraftKey] = useState(0);
  const back = () => setParams({ tab: "recent" });
  return (
    <div className={`chat-workspace${isNormalEditor ? " chat-workspace--normal-editor" : ""}`}>
      {configuring ? (
        <>
          <header className="conversation-setup__header">
            <Button variant="ghost" icon={<ArrowLeft aria-hidden className="button__icon" />} onClick={back}>
              {t("conversation.workspace")}
            </Button>
            <ConversationTypeBadge kind={activeKind} />
            {conversationId ? (
              <h1 className="conversation-setup__title">{t("conversation.settings")}</h1>
            ) : (
              <label className="conversation-setup__name conversation-setup__name--header">
                <span className="conversation-setup__name-label">{t("conversation.optionalTitle")}</span>
                <TextInput
                  value={title}
                  placeholder={t("conversation.titlePlaceholder")}
                  maxLength={120}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
            )}
          </header>
          <Suspense fallback={<p role="status">{t("common.loading")}</p>}>
            {conversationId && activeKind === "story" ? (
              <StorySettings key={conversationId} conversationId={conversationId} />
            ) : conversationId && activeKind === "novel" ? (
              <NovelSettings key={conversationId} conversationId={conversationId} />
            ) : conversationId || activeKind === "normal" ? (
              <NormalMode
                key={conversationId || draftKey}
                createOnly={!conversationId}
                conversationId={conversationId}
                conversationTitle={title}
                initializationService={conversationId ? undefined : initialization}
                onLaunchStarted={conversationId ? undefined : back}
                onApplied={conversationId ? undefined : mobileAccess.openChat}
              />
            ) : activeKind === "novel" ? (
              <NovelMode
                key={draftKey}
                conversationTitle={title}
                initializationService={initialization}
                onLaunchStarted={back}
                onLaunched={mobileAccess.openChat}
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
            setParams({ tab: "new", mode: selectedKind, conversation: id, kind: selectedKind })
          }
        />
      )}
      <ChatInitializationDialog
        error={initialization.initializationError}
        onClose={initialization.closeInitialization}
        open={initialization.initializationOpen}
        pending={initialization.initializationPending}
        task={initialization.initializationTask}
      />
      {mobileAccess.dialog}
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
              onClick={() => {
                setTitle(resolveConversationTitle(draftTitle));
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
          <span>{t("conversation.optionalTitle")}</span>
          <TextInput
            value={draftTitle}
            placeholder={t("conversation.titlePlaceholder")}
            maxLength={120}
            onChange={(event) => setDraftTitle(event.target.value)}
          />
        </label>
        <fieldset className="conversation-create__types">
          <legend>{t("conversation.chooseType")}</legend>
          <SegmentedRadio
            ariaLabel={t("conversation.chooseType")}
            name="conversation-kind"
            onChange={setKind}
            options={[
              {
                icon: <MessageCircle aria-hidden className="segmented-radio__icon" />,
                label: t("conversation.normal"),
                value: "normal",
              },
              {
                icon: <BookOpen aria-hidden className="segmented-radio__icon" />,
                label: t("conversation.story"),
                value: "story",
              },
              {
                icon: <ScrollText aria-hidden className="segmented-radio__icon" />,
                label: t("conversation.novel"),
                value: "novel",
              },
            ]}
            value={kind}
          />
          <p className="conversation-create__hint">{t(`conversation.${kind}Hint`)}</p>
        </fieldset>
      </Dialog>
    </div>
  );
}
