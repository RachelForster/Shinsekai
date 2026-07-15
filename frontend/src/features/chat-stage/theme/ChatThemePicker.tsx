import { useMemo, useRef, useState } from "react";
import { Check, Palette, RefreshCw, Trash2, Upload } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { Button, Dialog, IconButton, useToast } from "../../../shared/ui";
import { chatThemeDisplayName, type ChatThemeSummary } from "../../../shared/theme/chatTheme";
import { useOptionalChatTheme } from "./ChatThemeProvider";
import "./chat-theme-picker.css";

function ThemeSourceBadge({ source }: { source: ChatThemeSummary["source"] }) {
  const { t } = useI18n();
  return (
    <span className={`chat-theme-picker__badge chat-theme-picker__badge--${source}`}>
      {source === "builtin" ? t("chat.theme.sourceBuiltin") : t("chat.theme.sourceUser")}
    </span>
  );
}

function ThemeCard({
  active,
  busy,
  displayName,
  onDelete,
  onSwitch,
  theme,
}: {
  active: boolean;
  busy: boolean;
  displayName: string;
  onDelete: (theme: ChatThemeSummary) => void;
  onSwitch: (theme: ChatThemeSummary) => void;
  theme: ChatThemeSummary;
}) {
  const { t } = useI18n();
  const removable = theme.source === "user";

  return (
    <article className={`chat-theme-picker__card${active ? " chat-theme-picker__card--active" : ""}`}>
      {theme.previewUrl ? (
        <img alt="" className="chat-theme-picker__preview" src={theme.previewUrl} />
      ) : (
        <div aria-hidden className="chat-theme-picker__preview chat-theme-picker__preview--empty">
          <Palette className="chat-theme-picker__preview-icon" />
        </div>
      )}
      <div className="chat-theme-picker__meta">
        <div className="chat-theme-picker__title-row">
          <strong className="chat-theme-picker__title">{displayName}</strong>
          <ThemeSourceBadge source={theme.source} />
        </div>
        <div className="chat-theme-picker__subline">
          {theme.author ? <span>{theme.author}</span> : null}
          {theme.version ? <span>{theme.version}</span> : null}
        </div>
      </div>
      <div className="chat-theme-picker__actions">
        <Button
          disabled={busy || active}
          icon={
            active ? <Check aria-hidden className="button__icon" /> : <Palette aria-hidden className="button__icon" />
          }
          onClick={() => onSwitch(theme)}
          variant={active ? "ghost" : "primary"}
        >
          {active ? t("chat.theme.active") : t("chat.theme.apply")}
        </Button>
        {removable ? (
          <IconButton disabled={busy} label={t("chat.theme.delete")} onClick={() => onDelete(theme)}>
            <Trash2 aria-hidden className="icon-button__icon" />
          </IconButton>
        ) : null}
      </div>
    </article>
  );
}

interface ChatThemeManagerProps {
  onActiveThemeChange?: (id: string | null) => void;
  onThemesChange?: () => void;
}

export function ChatThemeManager({ onActiveThemeChange, onThemesChange }: ChatThemeManagerProps = {}) {
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const theme = useOptionalChatTheme();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<ChatThemeSummary | null>(null);
  const activeId = theme?.activeId ?? null;
  const themes = theme?.themes ?? [];
  const displayName = (item: ChatThemeSummary) => chatThemeDisplayName(item, language);

  const sortedThemes = useMemo(
    () =>
      [...themes].sort((left, right) => {
        if (left.id === activeId) {
          return -1;
        }
        if (right.id === activeId) {
          return 1;
        }
        if (left.source !== right.source) {
          return left.source === "builtin" ? -1 : 1;
        }
        return displayName(left).localeCompare(displayName(right));
      }),
    [activeId, displayName, themes],
  );

  if (!theme) {
    return null;
  }

  const { loading, refresh, removeTheme, switchTheme, uploadTheme } = theme;

  const handleSwitch = async (theme: ChatThemeSummary) => {
    setBusyId(theme.id);
    try {
      await switchTheme(theme.id);
      onActiveThemeChange?.(theme.id);
      showToast({ kind: "success", title: t("chat.theme.toast.applied"), message: displayName(theme) });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("common.operationFailed"),
        message: error instanceof Error ? error.message : t("chat.theme.error.apply"),
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleUpload = async (file: File | null) => {
    if (!file) {
      return;
    }
    setUploading(true);
    try {
      const summary = await uploadTheme(file);
      onThemesChange?.();
      showToast({ kind: "success", title: t("chat.theme.toast.uploaded"), message: displayName(summary) });
      await switchTheme(summary.id);
      onActiveThemeChange?.(summary.id);
      showToast({ kind: "success", title: t("chat.theme.toast.applied"), message: displayName(summary) });
    } catch (error) {
      showToast({
        kind: "error",
        title: t("common.importFailed"),
        message: error instanceof Error ? error.message : t("chat.theme.error.upload"),
      });
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleDelete = async () => {
    if (!deleteCandidate) {
      return;
    }
    setBusyId(deleteCandidate.id);
    try {
      await removeTheme(deleteCandidate.id);
      onThemesChange?.();
      if (deleteCandidate.id === activeId) {
        onActiveThemeChange?.(null);
      }
      showToast({ kind: "success", title: t("chat.theme.toast.deleted"), message: displayName(deleteCandidate) });
      setDeleteCandidate(null);
    } catch (error) {
      showToast({
        kind: "error",
        title: t("common.deleteFailed"),
        message: error instanceof Error ? error.message : t("chat.theme.error.delete"),
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <div className="chat-theme-manager">
        <div className="chat-theme-manager__toolbar">
          <input
            accept=".zip,application/zip"
            className="chat-theme-picker__file-input"
            onChange={(event) => handleUpload(event.target.files?.[0] ?? null)}
            ref={fileInputRef}
            type="file"
          />
          <Button
            disabled={uploading}
            icon={<Upload aria-hidden className="button__icon" />}
            onClick={() => fileInputRef.current?.click()}
            variant="primary"
          >
            {uploading ? t("chat.theme.uploading") : t("chat.theme.upload")}
          </Button>
          <Button
            disabled={loading}
            icon={<RefreshCw aria-hidden className="button__icon" />}
            onClick={() => {
              void refresh().then(() => onThemesChange?.());
            }}
          >
            {t("common.refresh")}
          </Button>
        </div>
        <div className="chat-theme-picker__grid">
          {sortedThemes.map((theme) => (
            <ThemeCard
              active={theme.id === activeId}
              busy={uploading || busyId === theme.id}
              displayName={displayName(theme)}
              key={theme.id}
              onDelete={setDeleteCandidate}
              onSwitch={handleSwitch}
              theme={theme}
            />
          ))}
        </div>
        {!sortedThemes.length ? <p className="chat-theme-picker__empty">{t("chat.theme.empty")}</p> : null}
      </div>
      <Dialog
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={() => setDeleteCandidate(null)}>{t("common.cancel")}</Button>
            <Button icon={<Trash2 aria-hidden className="button__icon" />} onClick={handleDelete} variant="danger">
              {t("chat.theme.delete")}
            </Button>
          </>
        }
        onClose={() => setDeleteCandidate(null)}
        open={Boolean(deleteCandidate)}
        title={t("chat.theme.deleteConfirmTitle")}
      >
        {t("chat.theme.deleteConfirmBody", { name: deleteCandidate ? displayName(deleteCandidate) : "" })}
      </Dialog>
    </>
  );
}

export function ChatThemePicker({
  className,
  onActiveThemeChange,
  onOpenChange,
  onThemesChange,
  open: controlledOpen,
}: ChatThemeManagerProps & {
  className?: string;
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
} = {}) {
  const { t } = useI18n();
  const theme = useOptionalChatTheme();
  const [internalOpen, setInternalOpen] = useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = (nextOpen: boolean) => {
    if (controlledOpen === undefined) {
      setInternalOpen(nextOpen);
    }
    onOpenChange?.(nextOpen);
  };

  if (!theme) {
    return null;
  }

  return (
    <>
      <IconButton className={className} label={t("chat.theme.open")} onClick={() => setOpen(true)}>
        <Palette aria-hidden className="icon-button__icon" />
      </IconButton>
      <Dialog
        bodyClassName="chat-theme-picker__dialog-body"
        closeLabel={t("common.close")}
        onClose={() => setOpen(false)}
        open={open}
        title={t("chat.theme.title")}
      >
        <ChatThemeManager onActiveThemeChange={onActiveThemeChange} onThemesChange={onThemesChange} />
      </Dialog>
    </>
  );
}
