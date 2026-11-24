import { Music, Save, Trash2, Upload } from "lucide-react";

import { fileUrl } from "../../../entities/files/repository";
import { baseName } from "../../../shared/assets/assetText";
import { useI18n } from "../../../shared/i18n";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  PathPickerDialog,
  TextInput,
  type PageSectionProps,
} from "../../../shared/ui";
import { AudioPlayer } from "../../../shared/ui/AudioPlayer";
import type { EffectPageContext } from "../effectContext";
import { useEffectAudioController } from "../controllers/useEffectAudioController";

export function EffectAudioSection({ ctx, id }: PageSectionProps<EffectPageContext>) {
  const { t } = useI18n();
  const audio = useEffectAudioController(ctx);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("effect.section.audio")}</h2>
        <div className="section__actions">
          <AsyncButton
            disabled={!audio.canDeleteSelected}
            icon={<Trash2 aria-hidden className="button__icon" />}
            loading={audio.batchDeletePending}
            onClick={audio.requestDeleteSelectedAudio}
            variant="danger"
          >
            {t("effect.asset.deleteSelectedAudio")}
          </AsyncButton>
          <Button
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={audio.requestClearAllAudio}
            variant="danger"
          >
            {t("effect.asset.clearAudio")}
          </Button>
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={ctx.savePending || audio.uploadAudioPending}
            onClick={audio.handleUploadAudio}
            variant="primary"
          >
            {t("effect.asset.uploadAudio")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={audio.saveAudioTagsPending}
            onClick={audio.saveAudioTags}
            variant="default"
          >
            {t("effect.action.saveAudioTags")}
          </AsyncButton>
        </div>
      </div>
      {ctx.draft.audio_list.length === 0 ? (
        <EmptyState title={t("effect.asset.emptyAudio")} />
      ) : (
        <div className="effect-audio-list">
          <div className="effect-audio-list__header">
            <label className="effect-audio-list__check effect-audio-list__check--header">
              <input
                aria-label={t("effect.asset.selectAllAudio")}
                checked={audio.allAudioSelected}
                onChange={audio.toggleAllAudioSelection}
                type="checkbox"
              />
            </label>
            <span className="effect-audio-list__index">{t("effect.asset.index")}</span>
            <span className="effect-audio-list__filename">{t("effect.asset.filename")}</span>
            <span className="effect-audio-list__prompt">{t("effect.asset.prompt")}</span>
            <span className="effect-audio-list__preview">{t("effect.asset.preview")}</span>
          </div>
          <div className="effect-audio-list__rows">
            {ctx.draft.audio_list.map((path, index) => {
              const filename = path ? baseName(path) || `${index + 1}` : `${index + 1}`;
              const fileSrc = fileUrl(path);
              const tagValue = audio.audioRowTags[index] ?? "";
              const isSelected = audio.selectedAudioIndexSet.has(index);

              return (
                <div className="effect-audio-row" key={`${path || index}-${index}`}>
                  <label className="effect-audio-list__check">
                    <input
                      aria-label={t("effect.asset.selectAudio", { index: index + 1 })}
                      checked={isSelected}
                      onChange={(event) => audio.toggleAudioSelection(index, event.target.checked)}
                      type="checkbox"
                    />
                  </label>
                  <span className="effect-audio-list__index">{index + 1}</span>
                  <span className="effect-audio-list__filename" title={path || undefined}>
                    <Music aria-hidden className="asset-row__icon" />
                    {filename}
                  </span>
                  <span className="effect-audio-list__prompt">
                    <TextInput
                      onChange={(event) => audio.updateAudioRowTag(index, event.target.value)}
                      value={tagValue}
                    />
                  </span>
                  <span className="effect-audio-list__preview">
                    <AudioPlayer compact label={`${t("effect.asset.preview")} ${filename}`} src={fileSrc} />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        multiple
        onClose={() => audio.setAudioUploadPickerOpen(false)}
        onSelect={(path) => audio.uploadAudio([path])}
        onSelectMany={(paths) => audio.uploadAudio(paths)}
        open={audio.audioUploadPickerOpen}
        title={t("effect.asset.uploadAudio")}
      />
      <AlertDialog
        body={audio.pendingDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={audio.pendingDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={audio.cancelPendingAudioDelete}
        onConfirm={audio.confirmPendingAudioDelete}
        open={audio.pendingAudioDeleteOpen}
        title={audio.pendingDeleteCopy?.title ?? t("common.delete")}
      />
    </section>
  );
}
