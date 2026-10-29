import { useState } from "react";
import { ExternalLink, FolderOpen } from "lucide-react";

import { openExternal, openT2iWorkflowFolder } from "../../entities/files/repository";
import { H3_MODEL_REPOSITORY_URL, H3_REQUIRED_MODELS, H3_SETUP_GUIDE_URL } from "../../shared/assets/t2iWorkflows";
import { useI18n } from "../../shared/i18n";
import { platformErrorCode } from "../../shared/platform/errors";
import { AsyncButton, Button, DataTable } from "../../shared/ui";

export function SpriteGenerationSetupGuide() {
  const { t } = useI18n();
  const [pending, setPending] = useState(false);
  const [folder, setFolder] = useState("");
  const [error, setError] = useState("");

  const showError = (failure: unknown) => {
    setError(
      platformErrorCode(failure) === "local_app_required"
        ? t("spriteGeneration.localFolderOnly")
        : t("spriteGeneration.resourcesFailed", {
            error: failure instanceof Error ? failure.message : String(failure),
          }),
    );
  };
  const openFolder = async () => {
    setPending(true);
    setError("");
    setFolder("");
    try {
      setFolder((await openT2iWorkflowFolder()).path);
    } catch (failure) {
      showError(failure);
    } finally {
      setPending(false);
    }
  };
  const openResource = async (url: string) => {
    setError("");
    try {
      await openExternal(url);
    } catch (failure) {
      showError(failure);
    }
  };
  const resourceLink = (url: string, label: string) => (
    <a
      href={url}
      rel="noreferrer"
      target="_blank"
      onClick={(event) => {
        event.preventDefault();
        void openResource(url);
      }}
    >
      {label}
    </a>
  );

  return (
    <div className="sprite-generation__resources">
      <div className="sprite-generation__toolbar">
        <AsyncButton
          icon={<FolderOpen aria-hidden className="button__icon" />}
          loading={pending}
          onClick={() => void openFolder()}
          variant="ghost"
        >
          {t("spriteGeneration.workflowFolder")}
        </AsyncButton>
        <Button
          icon={<ExternalLink aria-hidden className="button__icon" />}
          onClick={() => void openResource(H3_MODEL_REPOSITORY_URL)}
          title={H3_MODEL_REPOSITORY_URL}
          variant="ghost"
        >
          {t("spriteGeneration.modelDownloads")}
        </Button>
        <Button
          icon={<ExternalLink aria-hidden className="button__icon" />}
          onClick={() => void openResource(H3_SETUP_GUIDE_URL)}
          title={H3_SETUP_GUIDE_URL}
          variant="ghost"
        >
          {t("spriteGeneration.setupTutorial")}
        </Button>
      </div>
      {folder ? (
        <p className="sprite-generation__hint" role="status">
          {t("spriteGeneration.folderOpened", { path: folder })}
        </p>
      ) : null}
      {error ? (
        <p className="sprite-generation__error" role="alert">
          {error}
        </p>
      ) : null}
      <details>
        <summary className="sprite-generation__options">{t("spriteGeneration.setupGuide")}</summary>
        <ol className="sprite-generation__hint">
          <li>{t("spriteGeneration.setupServiceStep")}</li>
          <li>{t("spriteGeneration.setupConnectStep")}</li>
          <li>{t("spriteGeneration.setupTrialStep")}</li>
        </ol>
        <h3 className="sprite-generation__resource-title">{t("spriteGeneration.modelFiles")}</h3>
        <p className="sprite-generation__hint">{t("spriteGeneration.modelFilesHint")}</p>
        <p className="sprite-generation__hint">{resourceLink(H3_MODEL_REPOSITORY_URL, H3_MODEL_REPOSITORY_URL)}</p>
        <DataTable
          rows={H3_REQUIRED_MODELS}
          getRowKey={(model) => model.fileName}
          columns={[
            {
              key: "file",
              header: t("spriteGeneration.modelFile"),
              render: (model) => resourceLink(model.url, model.fileName),
            },
            {
              key: "folder",
              header: t("spriteGeneration.modelDestination"),
              render: (model) => <code>{model.folder}</code>,
            },
          ]}
        />
      </details>
    </div>
  );
}
