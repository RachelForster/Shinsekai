import { DownloadCloud } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type {
  TaskSnapshot,
  TtsBundleDownloadResult,
  TtsBundleKind,
  TtsBundleRecommendation,
  TtsGpuInfo,
} from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, Select, TaskProgress } from "../../shared/ui";

type Translate = ReturnType<typeof useI18n>["t"];

function normalizeGpuName(gpu: TtsGpuInfo, t: Translate) {
  const vendor = String(gpu.vendor || "").trim();
  const device = String(gpu.device || "").trim();
  const name =
    vendor && device && !device.toLowerCase().includes(vendor.toLowerCase()) ? `${vendor} ${device}` : device || vendor;
  return name.replace(/\s+/g, " ").trim() || t("api.tts.bundleUnknownGpu");
}

function formatGpuMemory(gpu: TtsGpuInfo, t: Translate) {
  const raw = gpu.vram_gb;
  if (raw == null || raw === "") {
    return t("api.tts.bundleGpuMemoryUnknown");
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    return t("api.tts.bundleGpuMemoryUnknown");
  }
  const formatted = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${formatted} GB`;
}

function formatTtsGpu(gpu: TtsGpuInfo, t: Translate) {
  return `${normalizeGpuName(gpu, t)} / ${formatGpuMemory(gpu, t)}`;
}

interface TtsBundleSectionProps {
  canCancelDownload: boolean;
  cancelPending: boolean;
  dialogOpen: boolean;
  downloadPending: boolean;
  error: string | null;
  kind: TtsBundleKind;
  onCancelDownload: () => void;
  onCloseDialog: () => void;
  onKindChange: (kind: TtsBundleKind) => void;
  onOpenDialog: () => void;
  onStartDownload: () => void;
  recommendation?: TtsBundleRecommendation;
  recommendationError: boolean;
  recommendationLoading: boolean;
  savePending: boolean;
  task: TaskSnapshot<TtsBundleDownloadResult> | null;
}

export function TtsBundleSection({
  canCancelDownload,
  cancelPending,
  dialogOpen,
  downloadPending,
  error,
  kind,
  onCancelDownload,
  onCloseDialog,
  onKindChange,
  onOpenDialog,
  onStartDownload,
  recommendation,
  recommendationError,
  recommendationLoading,
  savePending,
  task,
}: TtsBundleSectionProps) {
  const { t } = useI18n();
  const ttsBundleLabels: Record<TtsBundleKind, string> = {
    genie: t("api.tts.bundleGenie"),
    gptso: t("api.tts.bundleGptSovits"),
    gptso50: t("api.tts.bundleGptSovits50"),
  };
  const recommendedBundle = recommendation ? ttsBundleLabels[recommendation.kind] : "";
  const detectedGpuLabels = recommendation?.gpus.length ? recommendation.gpus.map((gpu) => formatTtsGpu(gpu, t)) : [];

  return (
    <>
      <section className="section">
        <div className="section__header">
          <div>
            <h2 className="section__title">{t("api.tts.bundleTitle")}</h2>
            <p className="section__description">{t("api.tts.bundleHint")}</p>
          </div>
          <div className="inline-actions">
            <Button
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              onClick={onOpenDialog}
              variant={downloadPending ? "primary" : "default"}
            >
              {downloadPending ? t("api.tts.bundleOpenRunning") : t("api.tts.bundleOpenDialog")}
            </Button>
          </div>
        </div>
      </section>
      <Dialog
        className="tts-bundle-dialog"
        closeLabel={t("api.tts.bundleClose")}
        footer={
          <>
            <Button onClick={onCloseDialog}>{t("api.tts.bundleClose")}</Button>
            {canCancelDownload ? (
              <AsyncButton loading={cancelPending} onClick={onCancelDownload} variant="danger">
                {t("api.tts.bundleCancel")}
              </AsyncButton>
            ) : null}
            <AsyncButton
              disabled={downloadPending}
              icon={<DownloadCloud aria-hidden className="button__icon" />}
              loading={downloadPending}
              onClick={onStartDownload}
              variant="primary"
            >
              {t("api.tts.bundleStart")}
            </AsyncButton>
          </>
        }
        onClose={onCloseDialog}
        open={dialogOpen}
        title={t("api.tts.bundleDialogTitle")}
      >
        <div className="tts-bundle-dialog__content">
          <p className="tts-bundle-dialog__intro">{t("api.tts.bundleDialogIntro")}</p>
          <div className="tts-bundle-summary" aria-live="polite">
            <div className="tts-bundle-summary__row">
              <span className="tts-bundle-summary__label">{t("api.tts.bundlePlatform")}</span>
              <span className="tts-bundle-summary__value">
                {recommendation?.platform || t("api.tts.bundleRecommendDetecting")}
              </span>
            </div>
            <div className="tts-bundle-summary__row">
              <span className="tts-bundle-summary__label">{t("api.tts.bundleDetectedGpu")}</span>
              <span className="tts-bundle-summary__value">
                {recommendationLoading ? t("api.tts.bundleRecommendDetecting") : null}
                {recommendationError ? t("api.tts.bundleRecommendFailed") : null}
                {!recommendationLoading && !recommendationError ? (
                  detectedGpuLabels.length ? (
                    <span className="tts-bundle-gpu-list">
                      {detectedGpuLabels.map((gpu) => (
                        <span className="tts-bundle-gpu-list__item" key={gpu}>
                          {gpu}
                        </span>
                      ))}
                    </span>
                  ) : (
                    t("api.tts.bundleRecommendNoGpu")
                  )
                ) : null}
              </span>
            </div>
            <div className="tts-bundle-summary__row tts-bundle-summary__row--recommend">
              <span className="tts-bundle-summary__label">{t("api.tts.bundleRecommended")}</span>
              <span className="tts-bundle-summary__value">{recommendedBundle || t("api.tts.bundleGenie")}</span>
            </div>
          </div>
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("api.tts.bundlePick")}</span>
            <span className="field-row__control">
              <Select
                disabled={downloadPending || savePending}
                onChange={(event) => onKindChange(event.target.value as TtsBundleKind)}
                value={kind}
              >
                <option value="genie">{t("api.tts.bundleGenie")}</option>
                <option value="gptso">{t("api.tts.bundleGptSovits")}</option>
                <option value="gptso50">{t("api.tts.bundleGptSovits50")}</option>
              </Select>
              <span className="field-row__help">{t("api.tts.bundleManualPick")}</span>
            </span>
          </label>
          {error ? (
            <div className="tts-bundle-status__error" role="alert">
              {error}
            </div>
          ) : null}
          {task ? (
            <div className="tts-bundle-status">
              <TaskProgress logLimit={0} task={task} />
            </div>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}
