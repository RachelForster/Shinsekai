import { Music, Save, Trash2, Upload } from "lucide-react";

import { baseName } from "../../shared/assets/assetText";
import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, EmptyState, Select, TextInput, useToast } from "../../shared/ui";
import { AudioPlayer } from "../../shared/ui/AudioPlayer";

interface AmbientEffectSectionProps {
  ambientAudioList: string[];
  ambientLayers: string[];
  ambientList: string[];
  ambientRowTags: string[];
  currentEffectName: string;
  deletingAmbient: boolean;
  onDeleteAmbient: (index: number) => void;
  onSaveAmbientTags: () => void;
  onSelectAmbientAudio: (index: number) => void;
  onUpdateAmbientLayer: (index: number, layer: string) => void;
  onUpdateAmbientRowTag: (index: number, value: string) => void;
  onUploadAmbient: () => void;
  savingEffect: boolean;
  savingTags: boolean;
  uploadingAmbient: boolean;
}

export function AmbientEffectSection({
  ambientAudioList,
  ambientLayers,
  ambientList,
  ambientRowTags,
  currentEffectName,
  deletingAmbient,
  onDeleteAmbient,
  onSaveAmbientTags,
  onSelectAmbientAudio,
  onUpdateAmbientLayer,
  onUpdateAmbientRowTag,
  onUploadAmbient,
  savingEffect,
  savingTags,
  uploadingAmbient,
}: AmbientEffectSectionProps) {
  const { t } = useI18n();
  const { showToast } = useToast();

  return (
    <section className="section page-section-anchor" id="effect-ambient">
      <div className="section__header">
        <h2 className="section__title">{t("effect.section.ambient")}</h2>
        <div className="section__actions">
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={savingEffect || uploadingAmbient}
            onClick={onUploadAmbient}
          >
            {t("effect.asset.uploadAmbient")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={savingTags}
            onClick={() => {
              if (!currentEffectName) {
                showToast({
                  kind: "error",
                  message: t("effect.validation.nameRequired"),
                  title: t("effect.action.saveAmbientTags"),
                });
                return;
              }
              onSaveAmbientTags();
            }}
            variant="ghost"
          >
            {t("effect.action.saveAmbientTags")}
          </AsyncButton>
        </div>
      </div>
      {ambientList.length === 0 ? (
        <EmptyState title={t("effect.asset.emptyAmbient")} />
      ) : (
        <div className="effect-image-list">
          {ambientList.map((path, index) => {
            const audioPath = ambientAudioList[index] ?? "";
            const layer = ambientLayers[index] === "front" ? "front" : "back";
            const isVideo = /\.(?:m4v|mov|mp4|webm)$/i.test(path);
            return (
              <div className="effect-image-row effect-image-row--ambient" key={`${path}-${index}`}>
                <figure className="effect-image-row__image">
                  {isVideo ? (
                    <video aria-label={baseName(path)} autoPlay loop muted playsInline src={fileUrl(path)} />
                  ) : (
                    <img alt={ambientRowTags[index] || baseName(path)} src={fileUrl(path)} />
                  )}
                  <figcaption title={path}>{baseName(path)}</figcaption>
                </figure>
                <div className="effect-image-row__controls">
                  <TextInput
                    onChange={(event) => onUpdateAmbientRowTag(index, event.target.value)}
                    value={ambientRowTags[index] ?? ""}
                  />
                  <AsyncButton
                    icon={<Save aria-hidden className="button__icon" />}
                    loading={savingTags}
                    onClick={onSaveAmbientTags}
                    variant="ghost"
                  >
                    {t("common.save")}
                  </AsyncButton>
                  <Select
                    aria-label={t("effect.ambient.layer")}
                    onChange={(event) => onUpdateAmbientLayer(index, event.target.value)}
                    value={layer}
                  >
                    <option value="back">{t("effect.ambient.layerBack")}</option>
                    <option value="front">{t("effect.ambient.layerFront")}</option>
                  </Select>
                  <Button
                    icon={<Music aria-hidden className="button__icon" />}
                    onClick={() => onSelectAmbientAudio(index)}
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
                    loading={deletingAmbient}
                    onClick={() => onDeleteAmbient(index)}
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
    </section>
  );
}
