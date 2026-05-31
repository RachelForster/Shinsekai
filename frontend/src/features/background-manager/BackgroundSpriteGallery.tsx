import { Image as ImageIcon, Save, Trash2, Upload } from "lucide-react";

import type { Background } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { ImageAssetGalleryItem } from "../../shared/ui";
import {
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  ImageAssetGallery,
  PathDisplay,
  TextInput,
} from "../../shared/ui";

interface BackgroundSpriteGalleryProps {
  currentBackgroundName: string;
  deletePending: boolean;
  imageRowTags: string[];
  onClearImages: () => void;
  onDeleteImage: (index: number) => void;
  onPendingImagePathsChange: (paths: string[]) => void;
  onSaveImageTags: () => void;
  onSelectImage: (index: number) => void;
  onUpdateImageTag: (index: number, value: string) => void;
  onUploadImages: () => void;
  pendingImagePaths: string[];
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
  onPendingImagePathsChange,
  onSaveImageTags,
  onSelectImage,
  onUpdateImageTag,
  onUploadImages,
  pendingImagePaths,
  saveTagsPending,
  selectedImageIndex,
  sprites,
  uploadPending,
}: BackgroundSpriteGalleryProps) {
  const { t } = useI18n();
  const selectedImage = sprites[selectedImageIndex];
  const backgroundImageItems: ImageAssetGalleryItem[] = sprites.map((sprite, index) => ({
    id: `${sprite.path}-${index}`,
    imageSrc: sprite.path ? fileUrl(sprite.path) : "",
    meta: imageRowTags[index] || "",
    title: sprite.path ? sprite.path.split(/[\\/]/).pop() || `${index + 1}` : `${index + 1}`,
  }));

  return (
    <section className="section background-images-section">
      <div className="section__header">
        <h2 className="section__title">{t("background.section.images")}</h2>
      </div>
      <div className="asset-editor">
        <div className="background-images-section__toolbar">
          <label className="field-row field-row--stack background-images-section__picker">
            <span className="field-row__label">{t("background.asset.selectImages")}</span>
            <span className="field-row__control">
              <FilePicker
                acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                multiple
                onPathsChange={(paths) => {
                  if (paths.length) {
                    onPendingImagePathsChange(paths);
                  }
                }}
                pickLabel={t("common.chooseFile")}
                pickerTitle={t("background.asset.selectImages")}
                value={
                  pendingImagePaths.length
                    ? t("background.asset.selectedFiles", { count: pendingImagePaths.length })
                    : ""
                }
              />
            </span>
          </label>
          <div className="background-images-section__actions">
            <AsyncButton
              disabled={!currentBackgroundName || !pendingImagePaths.length}
              icon={<Upload aria-hidden className="button__icon" />}
              loading={uploadPending}
              onClick={() => {
                if (!currentBackgroundName) {
                  return;
                }
                if (!pendingImagePaths.length) {
                  return;
                }
                onUploadImages();
              }}
            >
              {t("background.asset.uploadImages")}
            </AsyncButton>
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
        {!sprites.length ? <EmptyState title={t("background.asset.emptyImages")} /> : null}
        {selectedImage ? (
          <div className="asset-gallery-layout asset-gallery-layout--background">
            <ImageAssetGallery
              imageDecoding="sync"
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
    </section>
  );
}
