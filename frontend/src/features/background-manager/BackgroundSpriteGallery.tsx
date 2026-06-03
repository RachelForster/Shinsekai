import { useState } from "react";
import { Image as ImageIcon, Save, Tags, Trash2, Upload } from "lucide-react";

import type { Background } from "../../entities/config/types";
import { fileThumbnailUrl, fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { ImageAssetGalleryItem } from "../../shared/ui";
import {
  AsyncButton,
  Button,
  EmptyState,
  ImageAssetGallery,
  PathDisplay,
  PathPickerDialog,
  TextInput,
} from "../../shared/ui";

interface BackgroundSpriteGalleryProps {
  currentBackgroundName: string;
  deletePending: boolean;
  imageRowTags: string[];
  onClearImages: () => void;
  onDeleteImage: (index: number) => void;
  onOpenBulkTags: () => void;
  onSaveImageTags: () => void;
  onSelectImage: (index: number) => void;
  onUpdateImageTag: (index: number, value: string) => void;
  onUploadImages: (paths: string[]) => void;
  saveTagsPending: boolean;
  selectedImageIndex: number;
  sprites: Background["sprites"];
  uploadPending: boolean;
}

export function BackgroundSpriteGallery({
  currentBackgroundName,
  deletePending,
  imageRowTags,
  onClearImages,
  onDeleteImage,
  onOpenBulkTags,
  onSaveImageTags,
  onSelectImage,
  onUpdateImageTag,
  onUploadImages,
  saveTagsPending,
  selectedImageIndex,
  sprites,
  uploadPending,
}: BackgroundSpriteGalleryProps) {
  const { t } = useI18n();
  const [pickerOpen, setPickerOpen] = useState(false);
  const selectedImage = sprites[selectedImageIndex];
  const backgroundImageItems: ImageAssetGalleryItem[] = sprites.map((sprite, index) => ({
    id: `${sprite.path}-${index}`,
    imageSrc: sprite.path ? fileThumbnailUrl(sprite.path, 160) : "",
    meta: imageRowTags[index] || "",
    title: sprite.path ? sprite.path.split(/[\\/]/).pop() || `${index + 1}` : `${index + 1}`,
  }));

  return (
    <section className="section background-images-section">
      <div className="section__header">
        <h2 className="section__title">{t("background.section.images")}</h2>
        <div className="page__actions">
          <AsyncButton
            disabled={!currentBackgroundName}
            icon={<Upload aria-hidden className="button__icon" />}
            loading={uploadPending}
            onClick={() => setPickerOpen(true)}
            variant="ghost"
          >
            {t("background.asset.uploadImages")}
          </AsyncButton>
          <Button
            disabled={!sprites.length}
            icon={<Tags aria-hidden className="button__icon" />}
            onClick={onOpenBulkTags}
            variant="ghost"
          >
            {t("background.asset.batchImageTags")}
          </Button>
          <Button
            disabled={!currentBackgroundName || !sprites.length}
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={() => {
              if (!currentBackgroundName || !sprites.length) {
                return;
              }
              onClearImages();
            }}
            variant="ghost"
          >
            {t("background.asset.clearImages")}
          </Button>
        </div>
      </div>
      <div className="asset-editor">
        {!sprites.length ? <EmptyState title={t("background.asset.emptyImages")} /> : null}
        {selectedImage ? (
          <div className="asset-gallery-layout asset-gallery-layout--background">
            <ImageAssetGallery
              imageLoading="eager"
              items={backgroundImageItems}
              onSelect={onSelectImage}
              selectedIndex={selectedImageIndex}
            />
            <aside className="asset-inspector asset-inspector--background">
              <div className="asset-inspector__preview asset-inspector__preview--background">
                {selectedImage.path ? (
                  <img alt="" decoding="async" src={fileUrl(selectedImage.path)} />
                ) : (
                  <ImageIcon aria-hidden className="asset-inspector__fallback" />
                )}
              </div>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("background.asset.path")}</span>
                <span className="field-row__control">
                  <PathDisplay className="path-display--input" path={selectedImage.path} />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("background.asset.tag")}</span>
                <span className="field-row__control">
                  <TextInput
                    onChange={(event) => onUpdateImageTag(selectedImageIndex, event.target.value)}
                    value={imageRowTags[selectedImageIndex] ?? ""}
                  />
                </span>
              </label>
              <div className="asset-inspector__actions">
                <AsyncButton
                  icon={<Save aria-hidden className="button__icon" />}
                  loading={saveTagsPending}
                  onClick={onSaveImageTags}
                  variant="ghost"
                >
                  {t("background.action.saveImageTags")}
                </AsyncButton>
                <AsyncButton
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  loading={deletePending}
                  onClick={() => onDeleteImage(selectedImageIndex)}
                  variant="ghost"
                >
                  {t("common.remove")}
                </AsyncButton>
              </div>
            </aside>
          </div>
        ) : null}
      </div>
      <PathPickerDialog
        acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
        multiple
        onClose={() => setPickerOpen(false)}
        onSelect={(path) => {
          if (currentBackgroundName) {
            onUploadImages([path]);
          }
        }}
        onSelectMany={(paths) => {
          if (currentBackgroundName) {
            onUploadImages(paths);
          }
        }}
        open={pickerOpen}
        title={t("background.asset.selectImages")}
      />
    </section>
  );
}
