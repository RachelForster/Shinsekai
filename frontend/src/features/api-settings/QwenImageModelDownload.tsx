import { useEffect, useState } from "react";
import { DownloadCloud } from "lucide-react";

import { downloadModelAsset, getModelAssetStatus } from "../../entities/model-assets/repository";
import { useI18n } from "../../shared/i18n";
import type { ModelAssetStatus, TaskSnapshot } from "../../shared/platform/types";
import { AsyncButton, TaskProgress, useToast } from "../../shared/ui";

const MODEL = { assetId: "t2i.qwen-image-2.1" } as const;

export function QwenImageModelDownload({ disabled }: { disabled: boolean }) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [status, setStatus] = useState<ModelAssetStatus | null>(null);
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const [checkError, setCheckError] = useState("");
  useEffect(() => {
    let active = true;
    void getModelAssetStatus(MODEL)
      .then((value) => {
        if (active) setStatus(value);
      })
      .catch((error: unknown) => {
        if (active) setCheckError(error instanceof Error ? error.message : t("common.operationFailed"));
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [t]);
  const download = async () => {
    setBusy(true);
    setTask(null);
    try {
      await downloadModelAsset(MODEL, { onTaskUpdate: setTask });
      setStatus(await getModelAssetStatus(MODEL));
      setCheckError("");
      setTask(null);
    } catch (error) {
      showToast({
        kind: "error",
        title: "Qwen-Image-2.1",
        message: error instanceof Error ? error.message : t("common.operationFailed"),
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="field-row" aria-live="polite">
      <span className="field-row__label">{t("api.vision.modelStatus")}</span>
      <span className="field-row__control">
        <span>
          {checking
            ? t("api.vision.checkingModel")
            : checkError || (status?.cached ? t("api.vision.modelCached") : t("api.vision.modelMissing"))}
        </span>
        {!checking && !status?.cached ? (
          <AsyncButton
            disabled={disabled}
            icon={<DownloadCloud aria-hidden className="button__icon" />}
            loading={busy}
            onClick={() => void download()}
          >
            {t("api.vision.downloadModel")}
          </AsyncButton>
        ) : null}
        {task ? <TaskProgress logLimit={0} task={task} /> : null}
      </span>
    </div>
  );
}
