import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Image as ImageIcon, Save, Sparkles, Tags, Trash2, Upload } from "lucide-react";

import type { Background } from "../../entities/config/types";
import { fileThumbnailBatch, fileThumbnailUrl, fileUrl } from "../../entities/files/repository";
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
  autoLabelAvailable?: boolean;
  autoLabelDisabled?: boolean;
  autoLabelPending?: boolean;
  currentBackgroundName: string;
  deletePending: boolean;
  id?: string;
  imageRowTags: string[];
  onClearImages: () => void;
  onAutoLabel?: () => void;
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

const BACKGROUND_THUMBNAIL_BATCH_SIZE = 128;
const BACKGROUND_VISIBLE_IMAGE_INITIAL_COUNT = 96;
const BACKGROUND_VISIBLE_IMAGE_STEP = 96;

function visibleImageCountForSelection(total: number, selectedIndex: number) {
  if (total <= 0) {
    return 0;
  }
  return Math.min(total, Math.max(BACKGROUND_VISIBLE_IMAGE_INITIAL_COUNT, selectedIndex + 1));
}

export function BackgroundSpriteGallery({
  autoLabelAvailable = false,
  autoLabelDisabled = true,
  autoLabelPending = false,
  currentBackgroundName,
  deletePending,
  id,
  imageRowTags,
  onClearImages,
  onAutoLabel,
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
  const [thumbnailBatchReady, setThumbnailBatchReady] = useState(false);
  const [thumbnailSources, setThumbnailSources] = useState<Record<string, string>>({});
  const [visibleImageCount, setVisibleImageCount] = useState(() =>
    visibleImageCountForSelection(sprites.length, selectedImageIndex),
  );
  const selectedImage = sprites[selectedImageIndex];
  const spritePathKey = sprites
    .map((sprite) => sprite.path)
    .filter(Boolean)
    .join("\0");
  const previousSpritePathKey = useRef(spritePathKey);
  const visibleSprites = useMemo(() => sprites.slice(0, visibleImageCount), [sprites, visibleImageCount]);
  const spritePaths = useMemo(() => (spritePathKey ? [...new Set(spritePathKey.split("\0"))] : []), [spritePathKey]);
  const visibleSpritePathKey = visibleSprites
    .map((sprite) => sprite.path)
    .filter(Boolean)
    .join("\0");
  const visibleSpritePaths = useMemo(
    () => (visibleSpritePathKey ? [...new Set(visibleSpritePathKey.split("\0"))] : []),
    [visibleSpritePathKey],
  );
  const hasMoreImages = visibleImageCount < sprites.length;
  const loadMoreImages = useCallback(() => {
    setVisibleImageCount((current) => Math.min(sprites.length, current + BACKGROUND_VISIBLE_IMAGE_STEP));
  }, [sprites.length]);

  useEffect(() => {
    const requiredCount = visibleImageCountForSelection(sprites.length, selectedImageIndex);
    setVisibleImageCount((current) => {
      if (previousSpritePathKey.current !== spritePathKey) {
        return requiredCount;
      }
      return Math.min(sprites.length, Math.max(current, requiredCount));
    });
    previousSpritePathKey.current = spritePathKey;
  }, [selectedImageIndex, spritePathKey, sprites.length]);

  useEffect(() => {
    let cancelled = false;
    setThumbnailBatchReady(false);
    setThumbnailSources((current) => {
      const next: Record<string, string> = {};
      for (const path of spritePaths) {
        if (current[path]) {
          next[path] = current[path];
        }
      }
      return next;
    });
    if (!visibleSpritePaths.length) {
      setThumbnailBatchReady(true);
      return () => {
        cancelled = true;
      };
    }
    fileThumbnailBatch(visibleSpritePaths, 160, {
      batchSize: BACKGROUND_THUMBNAIL_BATCH_SIZE,
      delivery: "url",
      onBatch: (sources) => {
        if (!cancelled) {
          setThumbnailSources((current) => ({ ...current, ...sources }));
        }
      },
    })
      .then((sources) => {
        if (!cancelled) {
          setThumbnailSources((current) => ({ ...current, ...sources }));
          setThumbnailBatchReady(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setThumbnailSources({});
          setThumbnailBatchReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [spritePaths, visibleSpritePaths]);

  const backgroundImageItems: ImageAssetGalleryItem[] = visibleSprites.map((sprite, index) => ({
    id: `${sprite.path}-${index}`,
    imageSrc: sprite.path
      ? (thumbnailSources[sprite.path] ?? (thumbnailBatchReady ? fileThumbnailUrl(sprite.path, 160) : ""))
      : "",
    meta: imageRowTags[index] || "",
    title: sprite.path ? sprite.path.split(/[\\/]/).pop() || `${index + 1}` : `${index + 1}`,
  }));

  return (
    <section className="section background-images-section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("background.section.images")}</h2>
        <div className="page__actions">
          {autoLabelAvailable ? (
            <AsyncButton
              disabled={autoLabelDisabled}
              icon={<Sparkles aria-hidden className="button__icon" />}
              loading={autoLabelPending}
              onClick={onAutoLabel}
              variant="ghost"
            >
              {t("mediaAutoLabel.action")}
            </AsyncButton>
          ) : null}
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
            <div className="background-image-list">
              <ImageAssetGallery
                imageLoading="eager"
                items={backgroundImageItems}
                onNearEnd={hasMoreImages ? loadMoreImages : undefined}
                onSelect={onSelectImage}
                selectedIndex={selectedImageIndex}
              />
              {hasMoreImages ? (
                <Button className="background-image-list__more" onClick={loadMoreImages} variant="ghost">
                  {t("background.asset.loadMoreImages", {
                    shown: Math.min(visibleImageCount, sprites.length),
                    total: sprites.length,
                  })}
                </Button>
              ) : null}
            </div>
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
