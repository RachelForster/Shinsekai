import { TemplateEditorPage } from "../template-editor/TemplateEditorPage";
import { useEffect, useId, useState } from "react";
import { Pencil, Settings, Share2, Trash2 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { getPlatform } from "../../shared/platform/platform";
import type { ConversationSummary } from "../../shared/platform/types";
import { ConversationTypeBadge } from "./ConversationTypeBadge";
import { ActiveConversationPanel } from "./ActiveConversationPanel";
import { useI18n } from "../../shared/i18n";
import { Button, Dialog, IconButton, Select, Switch, TextInput } from "../../shared/ui";
import { useMobileAccessPreference } from "../mobile-access/useMobileAccessPreference";
import { useMobileAccessLaunch } from "../mobile-access/useMobileAccessLaunch";
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
  const [line, setLine] = useState("native");
  const [sharing, setSharing] = useState<ConversationSummary | null>(null);
  const [recipients, setRecipients] = useState<Array<{ id: string; name: string }>>([]);
  const [recipient, setRecipient] = useState("");
  const [sharePending, setSharePending] = useState(false);
  const [shareNotice, setShareNotice] = useState("");
  const [shareError, setShareError] = useState("");
  useEffect(() => {
    if (!sharing) return;
    let current = true;
    setRecipients([]);
    setRecipient("");
    setShareNotice("");
    setShareError("");
    const operation = getPlatform().chat.dokiPosts;
    if (!operation) {
      setShareError("当前版本不支持分享到 Doki，请更新后重试。");
      return;
    }
    operation({ action: "recipients" })
      .then((result) => {
        if (current) {
          setRecipients(result.characters || []);
          setRecipient(result.characters?.[0]?.id || "");
        }
      })
      .catch((reason) => {
        if (current) setShareError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      current = false;
    };
  }, [sharing]);
  const shareToDoki = async () => {
    if (!sharing || !recipient || sharePending) return;
    setSharePending(true);
    setShareError("");
    try {
      await getPlatform().chat.dokiPosts!({ action: "request", conversation_id: sharing.id, recipient_id: recipient });
      setShareNotice("已送到 Doki。请切回 Doki，预览生成的帖子后确认发送。");
    } catch (reason) {
      setShareError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSharePending(false);
    }
  };
  const [defaultsOpen, setDefaultsOpen] = useState(false);
  const client = useQueryClient();
  const [mobileAccessEnabled, setMobileAccessEnabled] = useMobileAccessPreference();
  const mobileAccess = useMobileAccessLaunch();
  const mobileAccessHintId = useId();
  const init = useChatInitialization();
  const guard = useChatLaunchGuard();
  const { runtimeLaunchDisabled, runtimeClosing, updateRuntimeStatusFromSnapshot } = guard;
  const conversations = useQuery({ queryKey: conversationsQueryKey, queryFn: listConversations, staleTime: 0 });
  const isEmpty = conversations.isSuccess && !conversations.data.length;
  const characters = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters });
  const [editing, setEditing] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const date = new Intl.DateTimeFormat(language.replace("_", "-"), { dateStyle: "medium", timeStyle: "short" });
  const openDoki = (id: string) => {
    window.location.hash = `/settings/templates?doki=${encodeURIComponent(id)}`;
  };
  const launch = async (item: ConversationSummary) => {
    if (item.dokiHandoffId) {
      openDoki(item.dokiHandoffId);
      return;
    }
    if (runtimeClosing || init.initializationPending) return;
    setError("");
    try {
      const snapshot = await init.runChatInitialization(async (options) => {
        if ((await getChatRuntimeStatus()).state !== "idle") throw new Error(t("story.launch.busy"));
        return launchChat(
          { ...(await prepareConversation(item.id)), enableMobileAccess: mobileAccessEnabled },
          options,
        );
      });
      client.setQueryData(chatQueryKey, snapshot);
      await updateRuntimeStatusFromSnapshot(snapshot);
      await mobileAccess.openChat(snapshot);
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
      <div className="conversation-line-actions" role="group" aria-label="聊天线路">
        {[
          ["daily", "Doki 日常线"],
          ["native", "Shinsekai 存档"],
        ].map(([value, label]) => (
          <Button key={value} variant={line === value ? "primary" : "ghost"} onClick={() => setLine(value)}>
            {label}
          </Button>
        ))}
        {line === "daily" && (
          <Button icon={<Settings aria-hidden className="button__icon" />} onClick={() => setDefaultsOpen(true)}>
            默认配置
          </Button>
        )}
      </div>
      <Dialog
        open={defaultsOpen}
        title="Doki 日常线默认配置"
        closeLabel={t("common.close")}
        onClose={() => setDefaultsOpen(false)}
        className="daily-default-dialog"
      >
        <TemplateEditorPage dokiDefaults />
      </Dialog>
      <div className="conversation-library__header">
        <h1>{t("conversation.workspace")}</h1>
        <div className="conversation-library__toolbar">
          <div className="conversation-library__mobile-access" title={t("mobileAccess.launchHint")}>
            <Switch
              checked={mobileAccessEnabled}
              disabled={runtimeClosing || init.initializationPending}
              aria-describedby={mobileAccessHintId}
              onChange={(event) => setMobileAccessEnabled(event.target.checked)}
            >
              {t("template.field.mobileAccess")}
            </Switch>
            <span id={mobileAccessHintId} className="visually-hidden">
              {t("mobileAccess.launchHint")}
            </span>
          </div>
          {!isEmpty && (
            <Button variant="primary" disabled={runtimeLaunchDisabled || init.initializationPending} onClick={onCreate}>
              {t("conversation.new")}
            </Button>
          )}
        </div>
      </div>
      <ActiveConversationPanel guard={guard} />
      {conversations.isPending && <p role="status">{t("common.loading")}</p>}
      {conversations.isError && <p role="alert">{conversations.error.message}</p>}
      {error && !editing && !deleting && <p role="alert">{error}</p>}
      {isEmpty && (
        <div className="conversation-library__empty">
          <img src="/chat-empty-catgirl.png" alt="" width={240} height={240} />
          <h2>{t("conversation.emptyGreeting")}</h2>
          <p>{t("conversation.empty")}</p>
          <Button variant="primary" disabled={runtimeLaunchDisabled || init.initializationPending} onClick={onCreate}>
            {t("conversation.new")}
          </Button>
        </div>
      )}
      {conversations.isError && <Button onClick={() => void conversations.refetch()}>{t("common.refresh")}</Button>}
      <div className="conversation-library__list">
        {conversations.data
          ?.filter((item) => (line === "daily" ? item.dokiTimeline === "daily" : item.dokiTimeline !== "daily"))
          .map((item) => {
            const character = characters.data?.find((entry) => item.characters.includes(entry.name));
            const sprite = character?.sprites[0]?.path;
            const name = item.title || t("conversation.untitled");
            return (
              <article className="conversation-card" key={item.id}>
                <ConversationAvatar name={character?.name || name} path={sprite} />
                <div className="conversation-card__content">
                  <h2>{name}</h2>
                  <div className="conversation-card__meta">
                    {item.dokiTimeline === "daily" ? (
                      <span className="conversation-type-badge">Doki 日常线</span>
                    ) : (
                      <ConversationTypeBadge kind={item.kind} />
                    )}
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
                      disabled={!item.storyPath || runtimeLaunchDisabled || init.initializationPending}
                    />
                  ) : (
                    <Button
                      variant="primary"
                      disabled={runtimeLaunchDisabled || init.initializationPending}
                      onClick={() => (item.hasSettings ? void launch(item) : onEdit(item.id, item.kind))}
                    >
                      {item.dokiEnded
                        ? "已结束"
                        : t(item.hasSettings ? "conversation.continue" : "conversation.configureAndContinue")}
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
                  <IconButton label="分享到 Doki" onClick={() => setSharing(item)}>
                    <Share2 aria-hidden className="icon-button__icon" />
                  </IconButton>
                  <IconButton
                    label={t("conversation.settings")}
                    onClick={() => (item.dokiHandoffId ? openDoki(item.dokiHandoffId) : onEdit(item.id, item.kind))}
                  >
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
        open={Boolean(sharing)}
        title="分享到 Doki"
        closeLabel={t("common.close")}
        dismissible={!sharePending}
        onClose={() => {
          if (!sharePending) setSharing(null);
        }}
        footer={
          <Button
            variant="primary"
            disabled={!recipient || sharePending || Boolean(shareNotice)}
            onClick={() => void shareToDoki()}
          >
            {sharePending ? "正在读取存档…" : "在 Doki 生成帖子"}
          </Button>
        }
      >
        <p>{sharing?.title || t("conversation.untitled")}</p>
        <p className="field-row__hint">
          根据存档的完整经过自动选择文风，写成可阅读、讨论的帖子。内容会先在 Doki 预览，不会直接发给角色。
        </p>
        <label className="field-row field-row--stack">
          <span className="field-row__label">分享给谁</span>
          <Select
            aria-label="分享给谁"
            value={recipient}
            disabled={sharePending || Boolean(shareNotice)}
            onChange={(event) => setRecipient(event.target.value)}
          >
            <option value="">请选择 Doki 角色</option>
            {recipients.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </Select>
        </label>
        {shareNotice && <p role="status">{shareNotice}</p>}
        {shareError && <p role="alert">{shareError}</p>}
      </Dialog>
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
      {mobileAccess.dialog}
    </section>
  );
}
