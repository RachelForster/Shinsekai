import { useEffect, useId, useState, type FormEvent } from "react";
import { Download, FolderOpen } from "lucide-react";

import { exportPlayableVn } from "../../../entities/chat/repository";
import { useI18n } from "../../../shared/i18n";
import { formatPlatformError } from "../../../shared/platform/errors";
import type { ChatVnExportFormat, ChatVnExportResult } from "../../../shared/platform/types";
import { Button, Dialog, Switch, TextInput } from "../../../shared/ui";
import "./VnExportDialog.css";

interface VnExportDialogProps {
  open: boolean;
  onClose: () => void;
  conversationId?: string;
  startEntryId?: string;
  endEntryId?: string;
  rangeCount?: number;
  defaultTitle?: string;
  defaultUserDisplayName?: string;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 1024) return `${Math.max(0, Math.round(bytes))} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function VnExportDialog({
  open,
  onClose,
  conversationId,
  startEntryId,
  endEntryId,
  rangeCount,
  defaultTitle = "",
  defaultUserDisplayName = "",
}: VnExportDialogProps) {
  const { t } = useI18n();
  const titleId = useId();
  const subtitleId = useId();
  const dirId = useId();
  const playerId = useId();

  const [title, setTitle] = useState(defaultTitle);
  const [subtitle, setSubtitle] = useState("");
  const [outputFormat, setOutputFormat] = useState<ChatVnExportFormat>("zip");
  const [outputDir, setOutputDir] = useState("");
  const [includeVoices, setIncludeVoices] = useState(true);
  const [transcodeMp3, setTranscodeMp3] = useState(true);
  const [includeBgm, setIncludeBgm] = useState(true);
  const [includeAmbient, setIncludeAmbient] = useState(true);
  const [userDisplayName, setUserDisplayName] = useState(defaultUserDisplayName);
  const [openFolder, setOpenFolder] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ChatVnExportResult | null>(null);

  useEffect(() => {
    if (!open) return;
    setTitle(defaultTitle);
    setSubtitle("");
    setOutputFormat("zip");
    setOutputDir("");
    setIncludeVoices(true);
    setTranscodeMp3(true);
    setIncludeBgm(true);
    setIncludeAmbient(true);
    setUserDisplayName(defaultUserDisplayName);
    setOpenFolder(false);
    setSubmitting(false);
    setError("");
    setResult(null);
  }, [open, conversationId, startEntryId, endEntryId, defaultTitle, defaultUserDisplayName]);

  const handleFormatChange = (next: ChatVnExportFormat) => {
    setOutputFormat(next);
    setOpenFolder(next === "directory");
  };

  const warningText = (code: string, res: ChatVnExportResult): string => {
    if (code === "ffmpeg_unavailable") return t("chat.vnExport.warning.ffmpegUnavailable");
    if (code === "skipped_non_static_sprites") {
      return t("chat.vnExport.warning.skippedNonStatic", { count: res.skippedNonStaticSprites });
    }
    if (code === "missing_assets_skipped") return t("chat.vnExport.warning.missingAssets");
    return code;
  };

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError("");
    setResult(null);
    try {
      const exported = await exportPlayableVn({
        ...(conversationId ? { conversationId } : {}),
        ...(startEntryId ? { startEntryId } : {}),
        ...(endEntryId ? { endEntryId } : {}),
        title: title.trim(),
        subtitle: subtitle.trim(),
        outputFormat,
        outputDir: outputDir.trim(),
        includeVoices,
        transcodeMp3: includeVoices && transcodeMp3,
        includeBgm,
        includeAmbient,
        userDisplayName: userDisplayName.trim(),
        openFolder,
      });
      setResult(exported);
    } catch (reason) {
      setError(formatPlatformError(reason, t));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      className="vn-export-dialog"
      closeLabel={t("common.close")}
      dismissible={!submitting}
      onClose={onClose}
      open={open}
      title={t("chat.vnExport.dialogTitle")}
      footer={
        result ? (
          <>
            <Button onClick={() => setResult(null)}>{t("chat.vnExport.back")}</Button>
            {result.downloadUrl ? (
              <a className="button button--primary vn-export-dialog__download" download href={result.downloadUrl}>
                <Download aria-hidden className="button__icon" />
                <span className="button__label">{t("chat.vnExport.downloadZip")}</span>
              </a>
            ) : null}
            <Button onClick={onClose}>{t("common.close")}</Button>
          </>
        ) : (
          <>
            <Button disabled={submitting} onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button loading={submitting} onClick={() => void handleSubmit()} variant="primary">
              {t(submitting ? "chat.vnExport.exporting" : "chat.vnExport.submit")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="vn-export-dialog__result">
          <p className="vn-export-dialog__ready">{t("chat.vnExport.readyTitle")}</p>
          <p className="vn-export-dialog__stats">
            {t("chat.vnExport.summaryStats", {
              assets: result.assetCount,
              entries: result.entryCount,
              mp3: result.transcodedVoiceCount,
              voices: result.voiceCount,
            })}
          </p>
          <p className="vn-export-dialog__size">
            {t("chat.vnExport.packageSize", {
              indexKb: Math.max(1, Math.round(result.indexHtmlBytes / 1024)),
              total: formatBytes(result.totalBytes),
            })}
          </p>
          <div className="vn-export-dialog__path">
            <FolderOpen aria-hidden size={15} />
            <code>{result.path}</code>
          </div>
          {result.warnings.length > 0 ? (
            <ul className="vn-export-dialog__warnings">
              {result.warnings.map((code) => (
                <li key={code}>{warningText(code, result)}</li>
              ))}
            </ul>
          ) : null}
          <p className="vn-export-dialog__hint">{t("chat.vnExport.toyHint")}</p>
        </div>
      ) : (
        <form className="vn-export-dialog__form" onSubmit={(event) => void handleSubmit(event)}>
          {typeof rangeCount === "number" && rangeCount > 0 ? (
            <p className="vn-export-dialog__hint">{t("chat.vnExport.rangeHint", { count: rangeCount })}</p>
          ) : null}
          <div className="vn-export-dialog__field">
            <label htmlFor={titleId}>{t("chat.vnExport.titleLabel")}</label>
            <TextInput
              id={titleId}
              maxLength={120}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t("chat.vnExport.titlePlaceholder")}
              value={title}
            />
          </div>
          <div className="vn-export-dialog__field">
            <label htmlFor={subtitleId}>{t("chat.vnExport.subtitleLabel")}</label>
            <TextInput
              id={subtitleId}
              maxLength={240}
              onChange={(event) => setSubtitle(event.target.value)}
              placeholder={t("chat.vnExport.subtitlePlaceholder")}
              value={subtitle}
            />
          </div>
          <fieldset className="vn-export-dialog__format">
            <legend>{t("chat.vnExport.formatLabel")}</legend>
            <label className="vn-export-dialog__radio">
              <input
                checked={outputFormat === "zip"}
                name="vnExportFormat"
                onChange={() => handleFormatChange("zip")}
                type="radio"
              />
              <span>{t("chat.vnExport.formatZip")}</span>
            </label>
            <label className="vn-export-dialog__radio">
              <input
                checked={outputFormat === "directory"}
                name="vnExportFormat"
                onChange={() => handleFormatChange("directory")}
                type="radio"
              />
              <span>{t("chat.vnExport.formatDirectory")}</span>
            </label>
          </fieldset>
          <div className="vn-export-dialog__field">
            <label htmlFor={dirId}>{t("chat.vnExport.outputDirLabel")}</label>
            <TextInput
              id={dirId}
              onChange={(event) => setOutputDir(event.target.value)}
              placeholder={t("chat.vnExport.outputDirPlaceholder")}
              value={outputDir}
            />
          </div>
          <div className="vn-export-dialog__field">
            <label htmlFor={playerId}>{t("chat.vnExport.playerNameLabel")}</label>
            <TextInput
              id={playerId}
              maxLength={24}
              onChange={(event) => setUserDisplayName(event.target.value)}
              placeholder={t("chat.vnExport.playerNamePlaceholder")}
              value={userDisplayName}
            />
          </div>
          <div className="vn-export-dialog__switches">
            <Switch checked={includeVoices} onChange={(event) => setIncludeVoices(event.target.checked)}>
              {t("chat.vnExport.includeVoices")}
            </Switch>
            {includeVoices ? (
              <Switch checked={transcodeMp3} onChange={(event) => setTranscodeMp3(event.target.checked)}>
                {t("chat.vnExport.transcodeMp3")}
              </Switch>
            ) : null}
            <Switch checked={includeBgm} onChange={(event) => setIncludeBgm(event.target.checked)}>
              {t("chat.vnExport.includeBgm")}
            </Switch>
            <Switch checked={includeAmbient} onChange={(event) => setIncludeAmbient(event.target.checked)}>
              {t("chat.vnExport.includeAmbient")}
            </Switch>
            <Switch checked={openFolder} onChange={(event) => setOpenFolder(event.target.checked)}>
              {t("chat.vnExport.openFolder")}
            </Switch>
          </div>
          {error ? (
            <p className="vn-export-dialog__error" role="alert">
              {error}
            </p>
          ) : null}
        </form>
      )}
    </Dialog>
  );
}
