import { useMemo, useState } from "react";
import { AlertTriangle, ClipboardCheck, ExternalLink, ScanLine, ShieldCheck } from "lucide-react";

import { browseFiles, openExternal } from "../../entities/files/repository";
import {
  buildPluginSubmissionIssueUrl,
  copyPluginSubmissionJson,
  scanLocalPlugin,
  validatePluginSubmission,
} from "../../entities/plugin/repository";
import type { PluginLocalScanResult, PluginSubmissionInput } from "../../entities/plugin/types";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Dialog, FilePicker, TextArea, TextInput, useToast } from "../../shared/ui";

const MAX_DESC_CHARS = 200;

interface PluginPublisherDialogProps {
  onClose: () => void;
  open: boolean;
}

interface PublisherFormState {
  author: string;
  desc: string;
  displayName: string;
  repo: string;
  shinsekaiVersion: string;
  socialLink: string;
  tags: string;
}

const emptyForm: PublisherFormState = {
  author: "",
  desc: "",
  displayName: "",
  repo: "",
  shinsekaiVersion: "",
  socialLink: "",
  tags: "",
};

function splitTags(value: string) {
  return value
    .split(/[,\s\uFF0C\u3001]+/g)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function buildSubmission(form: PublisherFormState): PluginSubmissionInput {
  return {
    author: form.author.trim(),
    desc: form.desc.trim(),
    display_name: form.displayName.trim(),
    lowest_shinsekai_version: form.shinsekaiVersion.trim() || undefined,
    repo: form.repo.trim(),
    social_link: form.socialLink.trim(),
    tags: splitTags(form.tags),
  };
}

function formatScanWarnings(scanResult: PluginLocalScanResult | null) {
  return scanResult?.warnings?.filter(Boolean) ?? [];
}

export function PluginPublisherDialog({ onClose, open }: PluginPublisherDialogProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [form, setForm] = useState<PublisherFormState>(emptyForm);
  const [localPath, setLocalPath] = useState("");
  const [scanResult, setScanResult] = useState<PluginLocalScanResult | null>(null);
  const [serverErrors, setServerErrors] = useState<string[]>([]);
  const [busyAction, setBusyAction] = useState<"copy" | "issue" | "scan" | "validate" | null>(null);
  const [payloadPreview, setPayloadPreview] = useState("");

  const submission = useMemo(() => buildSubmission(form), [form]);
  const previewJson = payloadPreview || JSON.stringify(submission, null, 2);
  const tagCount = submission.tags.length;
  const localErrors = useMemo(() => {
    const errors: string[] = [];
    if (form.desc.trim().length > MAX_DESC_CHARS) {
      errors.push("简介最多 200 字符。");
    }
    if (tagCount > 5) {
      errors.push("标签最多 5 个。");
    }
    return errors;
  }, [form.desc, tagCount]);
  const warnings = formatScanWarnings(scanResult);

  const updateForm = (field: keyof PublisherFormState, value: string) => {
    setPayloadPreview("");
    setServerErrors([]);
    setForm((current) => ({ ...current, [field]: value }));
  };

  const handleScan = async () => {
    if (!localPath.trim()) {
      setServerErrors(["请选择本地源码路径。"]);
      return;
    }
    setBusyAction("scan");
    try {
      const result = await scanLocalPlugin(localPath.trim());
      setScanResult(result);
      setServerErrors([]);
      setPayloadPreview("");
      setForm((current) => ({
        author: result.author || current.author,
        desc: result.desc || current.desc,
        displayName: result.display_name || current.displayName,
        repo: result.repo || current.repo,
        shinsekaiVersion: result.lowest_shinsekai_version || result.shinsekai_version || current.shinsekaiVersion,
        socialLink: result.social_link || current.socialLink,
        tags: result.tags?.length ? result.tags.join(", ") : current.tags,
      }));
      showToast({ kind: "success", title: t("plugin.publisher.scanDone") });
    } catch (error) {
      setServerErrors([error instanceof Error ? error.message : "读取元数据失败。"]);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("common.operationFailed"),
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleValidate = async () => {
    setBusyAction("validate");
    try {
      const result = await validatePluginSubmission(submission);
      setServerErrors(result.errors);
      if (result.json) {
        setPayloadPreview(result.json);
      }
      if (result.ok) {
        showToast({ kind: "success", title: t("plugin.publisher.validated") });
      }
      return result.ok;
    } catch (error) {
      setServerErrors([error instanceof Error ? error.message : "校验失败。"]);
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const handleCopy = async () => {
    setBusyAction("copy");
    try {
      const result = await copyPluginSubmissionJson(submission);
      setServerErrors([]);
      setPayloadPreview(result.json);
      showToast({ kind: "success", title: t("plugin.publisher.copied") });
    } catch (error) {
      setServerErrors([error instanceof Error ? error.message : "复制失败。"]);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("common.operationFailed"),
      });
    } finally {
      setBusyAction(null);
    }
  };

  const handleOpenIssue = async () => {
    setBusyAction("issue");
    try {
      const result = await buildPluginSubmissionIssueUrl(submission);
      setServerErrors([]);
      setPayloadPreview(result.json);
      await openExternal(result.issueUrl);
      showToast({ kind: "success", title: t("plugin.publisher.opened") });
    } catch (error) {
      setServerErrors([error instanceof Error ? error.message : "生成 Issue 链接失败。"]);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("common.operationFailed"),
      });
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <Dialog
      bodyClassName="plugin-publisher-dialog__body"
      className="plugin-publisher-dialog"
      closeLabel={t("common.close")}
      headerActions={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <AsyncButton
            disabled={localErrors.length > 0}
            icon={<ShieldCheck aria-hidden className="button__icon" />}
            loading={busyAction === "validate"}
            onClick={() => void handleValidate()}
          >
            {t("plugin.publisher.validate")}
          </AsyncButton>
          <AsyncButton
            disabled={localErrors.length > 0}
            icon={<ClipboardCheck aria-hidden className="button__icon" />}
            loading={busyAction === "copy"}
            onClick={() => void handleCopy()}
          >
            {t("plugin.publisher.copy")}
          </AsyncButton>
          <AsyncButton
            disabled={localErrors.length > 0}
            icon={<ExternalLink aria-hidden className="button__icon" />}
            loading={busyAction === "issue"}
            onClick={() => void handleOpenIssue()}
            variant="primary"
          >
            {t("plugin.publisher.githubIssue")}
          </AsyncButton>
        </>
      }
      onClose={onClose}
      open={open}
      title={t("plugin.publisher.title")}
    >
      <div className="plugin-publisher-dialog__intro">
        <p>{t("plugin.publisher.subtitle")}</p>
      </div>

      <section className="plugin-publisher-scan" aria-label={t("plugin.publisher.localPath")}>
        <label className="form-field plugin-publisher-scan__path">
          <span>{t("plugin.publisher.localPath")}</span>
          <FilePicker
            onPathChange={setLocalPath}
            pickLabel={t("plugin.publisher.localPath")}
            pickerBrowse={browseFiles}
            pickerMode="directory"
            pickerTitle={t("plugin.publisher.localPath")}
            readOnly
            value={localPath}
          />
        </label>
        <AsyncButton
          aria-label={t("plugin.publisher.scan")}
          icon={<ScanLine aria-hidden className="button__icon" />}
          loading={busyAction === "scan"}
          onClick={() => void handleScan()}
          variant="ghost"
        >
          {t("plugin.publisher.scan")}
        </AsyncButton>
      </section>

      <div className="plugin-publisher-layout">
        <form className="plugin-publisher-form" onSubmit={(event) => event.preventDefault()}>
          <label className="form-field">
            <span>{t("plugin.publisher.displayName")}</span>
            <TextInput
              autoComplete="off"
              onChange={(event) => updateForm("displayName", event.target.value)}
              placeholder="Shinsekai Plugin"
              value={form.displayName}
            />
          </label>
          <label className="form-field">
            <span>{t("plugin.publisher.author")}</span>
            <TextInput
              autoComplete="off"
              onChange={(event) => updateForm("author", event.target.value)}
              placeholder="Shinsekai Contributors"
              value={form.author}
            />
          </label>
          <label className="form-field plugin-publisher-form__wide">
            <span>{t("plugin.publisher.repo")}</span>
            <TextInput
              autoComplete="off"
              onChange={(event) => updateForm("repo", event.target.value)}
              placeholder="https://github.com/shinsekai/plugin-example"
              value={form.repo}
            />
          </label>
          <label className="form-field">
            <span>{t("plugin.publisher.shinsekaiVersion")}</span>
            <TextInput
              autoComplete="off"
              onChange={(event) => updateForm("shinsekaiVersion", event.target.value)}
              placeholder=">=0.2.0"
              value={form.shinsekaiVersion}
            />
          </label>
          <label className="form-field plugin-publisher-form__wide">
            <span>{t("plugin.publisher.desc")}</span>
            <TextArea
              maxLength={MAX_DESC_CHARS + 80}
              onChange={(event) => updateForm("desc", event.target.value)}
              placeholder="面向 Shinsekai 的示例插件，说明核心能力和适用场景。"
              rows={4}
              value={form.desc}
            />
            <span className="plugin-publisher-form__counter" data-invalid={form.desc.length > MAX_DESC_CHARS}>
              {t("plugin.publisher.descCount", { count: form.desc.length })}
            </span>
          </label>
          <label className="form-field">
            <span>{t("plugin.publisher.tags")}</span>
            <TextInput
              autoComplete="off"
              onChange={(event) => updateForm("tags", event.target.value)}
              placeholder="shinsekai, example"
              value={form.tags}
            />
          </label>
          <label className="form-field">
            <span>{t("plugin.publisher.socialLink")}</span>
            <TextInput
              autoComplete="off"
              onChange={(event) => updateForm("socialLink", event.target.value)}
              placeholder="你的 B 站、GitHub 主页或个人网站"
              value={form.socialLink}
            />
          </label>
        </form>

        <aside className="plugin-publisher-preview" aria-label={t("plugin.publisher.preview")}>
          <div className="plugin-publisher-preview__header">
            <strong>{t("plugin.publisher.preview")}</strong>
            <span>{tagCount} 个标签</span>
          </div>
          <pre>{previewJson}</pre>
          {[...localErrors, ...serverErrors].length ? (
            <div className="plugin-publisher-alert" role="alert">
              <AlertTriangle aria-hidden className="plugin-publisher-alert__icon" />
              <ul>
                {[...localErrors, ...serverErrors].map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {warnings.length ? (
            <div className="plugin-publisher-warnings">
              <strong>{t("plugin.publisher.warnings")}</strong>
              <ul>
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
      </div>
    </Dialog>
  );
}
