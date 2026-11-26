import { Music, Save, Trash2, Upload } from "lucide-react";

import { fileUrl } from "../../../entities/files/repository";
import { baseName } from "../../../shared/assets/assetText";
import { useI18n } from "../../../shared/i18n";
import {
  AsyncButton,
  Button,
  EmptyState,
  PathPickerDialog,
  Select,
  TextInput,
  type PageSectionProps,
} from "../../../shared/ui";
import { AudioPlayer } from "../../../shared/ui/AudioPlayer";
import type { EffectPageContext } from "../effectContext";
import { useEffectAmbientController } from "../controllers/useEffectAmbientController";

export function EffectAmbientSection({ ctx, id }: PageSectionProps<EffectPageContext>) {
  const { t } = useI18n();
  const ambient = useEffectAmbientController(ctx);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("effect.section.ambient")}</h2>
        <div className="section__actions">
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={ctx.savePending || ambient.uploadingAmbient}
            onClick={ambient.handleUploadAmbient}
          >
            {t("effect.asset.uploadAmbient")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={ambient.savingTags}
            onClick={ambient.saveAmbientTags}
            variant="ghost"
          >
            {t("effect.action.saveAmbientTags")}
          </AsyncButton>
        </div>
      </div>
      {ctx.draft.ambient_list.length === 0 ? (
        <EmptyState title={t("effect.asset.emptyAmbient")} />
      ) : (
        <div className="effect-image-list">
          {ctx.draft.ambient_list.map((path, index) => {
            const audioPath = ctx.draft.ambient_audio_list[index] ?? "";
            const layer = ctx.draft.ambient_layers[index] === "front" ? "front" : "back";
            const isVideo = /\.(?:m4v|mov|mp4|webm)$/i.test(path);
            return (
              <div className="effect-image-row effect-image-row--ambient" key={`${path}-${index}`}>
                <figure className="effect-image-row__image">
                  {isVideo ? (
                    <video aria-label={baseName(path)} autoPlay loop muted playsInline src={fileUrl(path)} />
                  ) : (
                    <img alt={ambient.ambientRowTags[index] || baseName(path)} src={fileUrl(path)} />
                  )}
                  <figcaption title={path}>{baseName(path)}</figcaption>
                </figure>
                <div className="effect-image-row__controls">
                  <TextInput
                    onChange={(event) => ambient.updateAmbientRowTag(index, event.target.value)}
                    value={ambient.ambientRowTags[index] ?? ""}
                  />
                  <AsyncButton
                    icon={<Save aria-hidden className="button__icon" />}
                    loading={ambient.savingTags}
                    onClick={ambient.saveRowAmbientTags}
                    variant="ghost"
                  >
                    {t("common.save")}
                  </AsyncButton>
                  <Select
                    aria-label={t("effect.ambient.layer")}
                    onChange={(event) => ambient.updateAmbientLayer(index, event.target.value)}
                    value={layer}
                  >
                    <option value="back">{t("effect.ambient.layerBack")}</option>
                    <option value="front">{t("effect.ambient.layerFront")}</option>
                  </Select>
                  <Button
                    icon={<Music aria-hidden className="button__icon" />}
                    onClick={() => ambient.setAmbientAudioTargetIndex(index)}
                    variant="ghost"
                  >
                    {t("effect.asset.insertAudio")}
                  </Button>
                  {audioPath ? (
                    <span className="effect-image-row__audio" title={audioPath}>
                      <small>{baseName(audioPath)}</small>
                      <AudioPlayer
                        compact
                        label={`${t("effect.asset.preview")} ${baseName(audioPath)}`}
                        src={fileUrl(audioPath)}
                      />
                    </span>
                  ) : null}
                  <AsyncButton
                    icon={<Trash2 aria-hidden className="button__icon" />}
                    loading={ambient.deletingAmbient}
                    onClick={() => ambient.deleteAmbient(index)}
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
        acceptedExtensions={[".apng", ".gif", ".jpeg", ".jpg", ".m4v", ".mov", ".mp4", ".png", ".webm", ".webp"]}
        multiple
        onClose={() => ambient.setAmbientUploadPickerOpen(false)}
        onSelect={(path) => ambient.uploadAmbient([path])}
        onSelectMany={(paths) => ambient.uploadAmbient(paths)}
        open={ambient.ambientUploadPickerOpen}
        title={t("effect.asset.uploadAmbient")}
      />
      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        onClose={() => ambient.setAmbientAudioTargetIndex(null)}
        onSelect={ambient.uploadAmbientAudio}
        open={ambient.ambientAudioTargetIndex !== null}
        title={t("effect.asset.insertAudio")}
      />
    </section>
  );
}
