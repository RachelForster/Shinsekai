import { Music, Save, Trash2, Upload } from "lucide-react";

import { fileUrl } from "../../../entities/files/repository";
import { baseName } from "../../../shared/assets/assetText";
import { useI18n } from "../../../shared/i18n";
import {
  AsyncButton,
  Button,
  EmptyState,
  PathPickerDialog,
  TextInput,
  type PageSectionProps,
} from "../../../shared/ui";
import { AudioPlayer } from "../../../shared/ui/AudioPlayer";
import type { EffectPageContext } from "../effectContext";
import { useEffectImagesController } from "../controllers/useEffectImagesController";

export function EffectImagesSection({ ctx, id }: PageSectionProps<EffectPageContext>) {
  const { t } = useI18n();
  const images = useEffectImagesController(ctx);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("effect.section.image")}</h2>
        <div className="section__actions">
          <label className="effect-image-batch-select">
            <input
              checked={images.allImagesSelected}
              disabled={!ctx.draft.image_list.length}
              onChange={images.toggleAllImageSelection}
              type="checkbox"
            />
            <span>{t("effect.asset.selectAllImages")}</span>
          </label>
          <AsyncButton
            disabled={!images.selectedImageIndexes.length}
            icon={<Music aria-hidden className="button__icon" />}
            loading={images.batchAudioPending}
            onClick={() => images.setImageAudioBatchPickerOpen(true)}
            variant="ghost"
          >
            {t("effect.asset.batchInsertAudio")}
          </AsyncButton>
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={ctx.savePending || images.uploadImagePending}
            onClick={images.handleUploadImage}
            variant="primary"
          >
            {t("effect.asset.uploadImage")}
          </AsyncButton>
        </div>
      </div>
      {ctx.draft.image_list.length === 0 ? (
        <EmptyState title={t("effect.asset.emptyImage")} />
      ) : (
        <div className="effect-image-list">
          {ctx.draft.image_list.map((path, index) => {
            const audioPath = ctx.draft.image_audio_list[index] ?? "";
            const imageName = baseName(path);
            const audioName = baseName(audioPath);
            const isSelected = images.selectedImageIndexSet.has(index);
            return (
              <div className="effect-image-row" key={`${path}-${index}`}>
                <label className="effect-image-row__check">
                  <input
                    aria-label={t("effect.asset.selectImage", { index: index + 1 })}
                    checked={isSelected}
                    onChange={(event) => images.toggleImageSelection(index, event.target.checked)}
                    type="checkbox"
                  />
                </label>
                <figure className="effect-image-row__image">
                  <img alt={images.imageRowTags[index] || imageName} src={fileUrl(path)} />
                  <figcaption title={path}>{imageName}</figcaption>
                </figure>
                <div className="effect-image-row__controls">
                  <TextInput
                    onChange={(event) => images.updateImageRowTag(index, event.target.value)}
                    value={images.imageRowTags[index] ?? ""}
                  />
                  <AsyncButton
                    icon={<Save aria-hidden className="button__icon" />}
                    loading={images.saveImageTagsPending}
                    onClick={images.saveImageTags}
                    variant="ghost"
                  >
                    {t("effect.action.saveImageTags")}
                  </AsyncButton>
                  <Button
                    icon={<Music aria-hidden className="button__icon" />}
                    onClick={() => images.setImageAudioTargetIndex(index)}
                    variant="ghost"
                  >
                    {t("effect.asset.insertAudio")}
                  </Button>
                  {audioPath ? (
                    <span className="effect-image-row__audio" title={audioPath}>
                      <small>{audioName}</small>
                      <AudioPlayer
                        compact
                        label={`${t("effect.asset.preview")} ${audioName}`}
                        src={fileUrl(audioPath)}
                      />
                    </span>
                  ) : null}
                  <AsyncButton
                    icon={<Trash2 aria-hidden className="button__icon" />}
                    loading={images.deleteImagePending}
                    onClick={() => images.deleteImage(index)}
                    variant="danger"
                  >
                    {t("common.delete")}
                  </AsyncButton>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <PathPickerDialog
        acceptedExtensions={[".jpeg", ".jpg", ".png"]}
        multiple
        onClose={() => images.setImageUploadPickerOpen(false)}
        onSelect={(path) => images.uploadImages([path])}
        onSelectMany={(paths) => images.uploadImages(paths)}
        open={images.imageUploadPickerOpen}
        title={t("effect.asset.uploadImage")}
      />
      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        onClose={() => images.setImageAudioBatchPickerOpen(false)}
        onSelect={images.uploadBatchAudio}
        open={images.imageAudioBatchPickerOpen}
        title={t("effect.asset.batchInsertAudio")}
      />
      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        onClose={() => images.setImageAudioTargetIndex(null)}
        onSelect={images.uploadSingleImageAudio}
        open={images.imageAudioTargetIndex !== null}
        title={t("effect.asset.insertAudio")}
      />
    </section>
  );
}
