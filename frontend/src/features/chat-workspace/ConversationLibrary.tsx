import { useState } from "react";
import { Pencil, Settings, Trash2 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import {
  chatQueryKey,
  conversationsQueryKey,
  getChatRuntimeStatus,
  launchChat,
  listConversations,
  prepareConversation,
  renameConversation,
  deleteConversation,
} from "../../entities/chat/repository";
import { fileThumbnailUrl } from "../../entities/files/repository";
import type { ConversationSummary } from "../../shared/platform/types";
import { ConversationTypeBadge } from "./ConversationTypeBadge";
import { showChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import { Button, Dialog, IconButton, TextInput } from "../../shared/ui";
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { useChatInitialization } from "../chat-startup/useChatInitialization";
import { useChatLaunchGuard } from "../chat-startup/useChatLaunchGuard";
import { StoryLaunchButton } from "../story-generator/components/StoryLaunchButton";
import "./ConversationLibrary.css";

function ConversationAvatar({ name, path }: { name: string; path?: string }) {
  const [failedPath, setFailedPath] = useState<string>();
  return (
    <div className="conversation-card__avatar" aria-hidden="true">
      {path && path !== failedPath ? (
        <img src={fileThumbnailUrl(path, 128)} alt="" loading="lazy" onError={() => setFailedPath(path)} />
      ) : (
        name.slice(0, 1)
      )}
    </div>
  );
}

export function ConversationLibrary({
  onCreate,
  onEdit,
}: {
  onCreate: () => void;
  onEdit: (id: string, kind?: ConversationSummary["kind"]) => void;
}) {
  const { t, language } = useI18n();
  const client = useQueryClient();
  const navigate = useNavigate();
  const init = useChatInitialization();
  const { runtimeClosing, updateRuntimeStatusFromSnapshot } = useChatLaunchGuard();
  const conversations = useQuery({ queryKey: conversationsQueryKey, queryFn: listConversations, staleTime: 0 });
  const isEmpty = conversations.isSuccess && !conversations.data.length;
  const characters = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters });
  const [editing, setEditing] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const date = new Intl.DateTimeFormat(language.replace("_", "-"), { dateStyle: "medium", timeStyle: "short" });
  const launch = async (item: ConversationSummary) => {
    if (runtimeClosing || init.initializationPending) return;
    setError("");
    try {
      const snapshot = await init.runChatInitialization(async (options) => {
        if ((await getChatRuntimeStatus()).state !== "idle") throw new Error(t("story.launch.busy"));
        return launchChat(await prepareConversation(item.id), options);
      });
      client.setQueryData(chatQueryKey, snapshot);
      await updateRuntimeStatusFromSnapshot(snapshot);
      await showChatSurface({ navigate, snapshot });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  const rename = async () => {
    if (!editing || saving) return;
    setSaving(true);
    setError("");
    try {
      await renameConversation(editing.id, title);
      await client.invalidateQueries({ queryKey: conversationsQueryKey });
      setEditing(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    if (!deleting || saving) return;
    setSaving(true);
    setError("");
    try {
      await deleteConversation(deleting.id);
      await client.invalidateQueries({ queryKey: conversationsQueryKey });
      setDeleting(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="conversation-library">
      <div className="conversation-library__header">
        <h1>{t("conversation.workspace")}</h1>
        {!isEmpty && (
          <Button variant="primary" disabled={runtimeClosing} onClick={onCreate}>
            {t("conversation.new")}
          </Button>
        )}
      </div>
      {conversations.isPending && <p role="status">{t("common.loading")}</p>}
      {conversations.isError && <p role="alert">{conversations.error.message}</p>}
      {error && !editing && !deleting && <p role="alert">{error}</p>}
      {isEmpty && (
        <div className="conversation-library__empty">
          <img src="/chat-empty-catgirl.png" alt="" width={240} height={240} />
          <h2>{t("conversation.emptyGreeting")}</h2>
          <p>{t("conversation.empty")}</p>
          <Button variant="primary" disabled={runtimeClosing} onClick={onCreate}>
            {t("conversation.new")}
          </Button>
        </div>
      )}
      {conversations.isError && <Button onClick={() => void conversations.refetch()}>{t("common.refresh")}</Button>}
      <div className="conversation-library__list">
        {conversations.data?.map((item) => {
          const character = characters.data?.find((entry) => item.characters.includes(entry.name));
          const sprite = character?.sprites[0]?.path;
          const name = item.title || t("conversation.untitled");
          return (
            <article className="conversation-card" key={item.id}>
              <ConversationAvatar name={character?.name || name} path={sprite} />
              <div className="conversation-card__content">
                <h2>{name}</h2>
                <div className="conversation-card__meta">
                  <ConversationTypeBadge kind={item.kind} />
                  <span>{item.characters.join(" · ")}</span>
                  <time dateTime={new Date(item.updatedAt).toISOString()}>{date.format(item.updatedAt)}</time>
                </div>
                <p className="conversation-card__preview">{item.preview || t("conversation.noMessages")}</p>
              </div>
              <div className="conversation-card__actions">
                {item.kind === "story" && !item.requiresCharacterSelection ? (
                  <StoryLaunchButton
                    storyPath={item.storyPath}
                    historyPath={item.historyPath}
                    conversationId={item.hasSettings ? item.id : undefined}
                    label={t("conversation.continue")}
                    disabled={!item.storyPath || runtimeClosing || init.initializationPending}
                  />
                ) : (
                  <Button
                    variant="primary"
                    disabled={runtimeClosing || init.initializationPending}
                    onClick={() => (item.hasSettings ? void launch(item) : onEdit(item.id, item.kind))}
                  >
                    {t(item.hasSettings ? "conversation.continue" : "conversation.configureAndContinue")}
                  </Button>
                )}
                <IconButton
                  label={t("conversation.rename")}
                  onClick={() => {
                    setEditing(item);
                    setTitle(name);
                    setError("");
                  }}
                >
                  <Pencil aria-hidden className="icon-button__icon" />
                </IconButton>
                <IconButton label={t("conversation.settings")} onClick={() => onEdit(item.id, item.kind)}>
                  <Settings aria-hidden className="icon-button__icon" />
                </IconButton>
                <IconButton
                  label={t("common.delete")}
                  onClick={() => {
                    setDeleting(item);
                    setError("");
                  }}
                >
                  <Trash2 aria-hidden className="icon-button__icon" />
                </IconButton>
              </div>
              {item.kind === "story" && !item.storyPath && <p role="status">{t("conversation.missingStory")}</p>}
            </article>
          );
        })}
      </div>
      <Dialog
        open={Boolean(editing)}
        title={t("conversation.rename")}
        closeLabel={t("common.close")}
        onClose={() => {
          if (!saving) setEditing(null);
        }}
        footer={
          <Button disabled={saving || !title.trim()} onClick={() => void rename()}>
            {t("common.save")}
          </Button>
        }
      >
        <TextInput
          aria-label={t("conversation.title")}
          maxLength={120}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        {error && <p role="alert">{error}</p>}
      </Dialog>
      <Dialog
        open={Boolean(deleting)}
        title={t("conversation.delete")}
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
        <p>{t("conversation.deleteConfirm", { title: deleting?.title || t("conversation.untitled") })}</p>
        {error && <p role="alert">{error}</p>}
      </Dialog>
      <ChatInitializationDialog
        error={init.initializationError}
        onClose={init.closeInitialization}
        open={init.initializationOpen}
        pending={init.initializationPending}
        task={init.initializationTask}
      />
    </section>
  );
}
