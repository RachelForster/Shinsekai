import { useEffect, useRef, useState } from "react";

import { tagContents } from "../assets/assetText";
import { useI18n } from "../i18n";
import type { Character, PortraitCrop } from "../platform/types";
import { Button, Dialog, Select, Switch } from "../ui";
import { Portrait, applyPortraitCrop, defaultPortraitCrop, normalizePortraitCrop, portraitGeometry } from "./Portrait";

export interface PortraitCropDialogProps {
  character: Character | null;
  open: boolean;
  initialSpriteIndex?: number;
  saveSelectedAsDefaultPortrait?: boolean;
  title?: string;
  saving?: boolean;
  error?: string;
  onClose: () => void;
  onSave: (nextCharacter: Character) => void | Promise<void>;
}

export function PortraitCropDialog({
  character,
  open,
  initialSpriteIndex = 0,
  saveSelectedAsDefaultPortrait = false,
  title,
  saving = false,
  error,
  onClose,
  onSave,
}: PortraitCropDialogProps) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<Character | null>(null);
  const [index, setIndex] = useState(0);
  const [individual, setIndividual] = useState(false);
  const [crop, setCrop] = useState<PortraitCrop>(defaultPortraitCrop);
  const image = useRef({ width: 1, height: 1 });
  const drag = useRef<{ x: number; y: number; crop: PortraitCrop } | null>(null);

  const selectSprite = (nextIndex: number, value: Character) => {
    const clampedIndex = Math.min(Math.max(0, nextIndex), Math.max(0, value.sprites.length - 1));
    setIndex(clampedIndex);
    const override = value.sprites[clampedIndex]?.portrait_crop;
    setIndividual(Boolean(override));
    setCrop(normalizePortraitCrop(override ?? value.portrait_crop ?? defaultPortraitCrop));
    drag.current = null;
  };

  useEffect(() => {
    if (!open || !character) {
      setEditing(null);
      drag.current = null;
      return;
    }
    const next = structuredClone(character);
    setEditing(next);
    selectSprite(initialSpriteIndex, next);
  }, [character, initialSpriteIndex, open]);

  const updateCrop = (nextCrop: PortraitCrop) => {
    const normalized = normalizePortraitCrop(nextCrop);
    setCrop(normalized);
    setEditing((value) => {
      if (!value) return value;
      return applyPortraitCrop(value, index, individual, normalized);
    });
  };

  const activeSprite = editing?.sprites[index];
  const tags = editing ? tagContents(editing.emotion_tags, editing.sprites.length) : [];

  return (
    <Dialog
      closeLabel={t("common.close")}
      dismissible={!saving}
      footer={
        <>
          <Button disabled={saving} onClick={() => updateCrop({ ...defaultPortraitCrop })}>
            {t("player.reset")}
          </Button>
          <Button
            disabled={saving || !editing}
            onClick={() => {
              if (editing) {
                const payload = saveSelectedAsDefaultPortrait ? { ...editing, portrait_sprite_index: index } : editing;
                void onSave(payload);
              }
            }}
            variant="primary"
          >
            {t("common.save")}
          </Button>
        </>
      }
      onClose={() => {
        if (!saving) {
          onClose();
        }
      }}
      open={open && Boolean(editing)}
      title={title ?? t("character.sprite.portraitCropTitle")}
    >
      {editing && activeSprite ? (
        <div className="portrait-crop-dialog__body">
          <Select
            aria-label={t("player.sprite")}
            disabled={saving}
            onChange={(event) => selectSprite(Number(event.target.value), editing)}
            value={index}
          >
            {editing.sprites.map((sprite, spriteIndex) => {
              const fileLabel = sprite.path.split(/[\\/]/).pop() || `${spriteIndex + 1}`;
              const tagLabel = tags[spriteIndex]?.trim();
              return (
                <option key={`${sprite.path}-${spriteIndex}`} value={spriteIndex}>
                  {spriteIndex + 1} · {fileLabel}
                  {tagLabel ? ` (${tagLabel})` : ""}
                </option>
              );
            })}
          </Select>

          <p className="portrait-crop-dialog__hint">{t("character.sprite.portraitCropHint")}</p>

          <div className="portrait-crop-dialog__workspace">
            <div className="portrait-crop-dialog__previews">
              <Portrait
                className="portrait-crop-dialog__stage"
                crop={crop}
                name={editing.name}
                onImageSize={(width, height) => {
                  image.current = { width, height };
                }}
                onPointerDown={(event) => {
                  if (saving) return;
                  event.currentTarget.setPointerCapture?.(event.pointerId);
                  drag.current = { x: event.clientX, y: event.clientY, crop };
                }}
                onPointerMove={(event) => {
                  const start = drag.current;
                  if (!start || !event.buttons || saving) return;
                  const { width, height } = image.current;
                  const side = portraitGeometry(width, height, start.crop).side;
                  const hostWidth = Math.max(1, event.currentTarget.clientWidth || 200);
                  const scale = hostWidth / side;
                  const initial = portraitGeometry(width, height, start.crop);
                  updateCrop({
                    ...start.crop,
                    x: Math.max(
                      side / (2 * width),
                      Math.min(
                        1 - side / (2 * width),
                        (initial.left + side / 2) / width - (event.clientX - start.x) / (scale * width),
                      ),
                    ),
                    y: Math.max(
                      side / (2 * height),
                      Math.min(
                        1 - side / (2 * height),
                        (initial.top + side / 2) / height - (event.clientY - start.y) / (scale * height),
                      ),
                    ),
                  });
                }}
                onWheel={(event) => {
                  if (saving) return;
                  event.preventDefault();
                  const delta = event.deltaY < 0 ? 0.15 : -0.15;
                  updateCrop({ ...crop, zoom: Math.min(8, Math.max(1, Number((crop.zoom + delta).toFixed(2)))) });
                }}
                path={activeSprite.path}
                shape="square"
                size={200}
              />
              <div aria-hidden="true" className="portrait-crop-dialog__mini-row">
                <Portrait
                  active={false}
                  alt=""
                  ariaHidden
                  className="portrait-crop-dialog__mini-preview"
                  crop={crop}
                  name={editing.name}
                  path={activeSprite.path}
                  shape="circle"
                  size={44}
                />
                <Portrait
                  active={false}
                  alt=""
                  ariaHidden
                  className="portrait-crop-dialog__mini-preview portrait-crop-dialog__mini-preview--card"
                  crop={crop}
                  name={editing.name}
                  path={activeSprite.path}
                  shape="fill"
                />
              </div>
            </div>

            <div className="portrait-crop-dialog__controls">
              {(["x", "y", "zoom"] as const).map((key) => (
                <label className="portrait-crop-dialog__slider-label" key={key}>
                  <span className="portrait-crop-dialog__slider-header">
                    <span>{t(`player.${key}`)}</span>
                    <span className="portrait-crop-dialog__slider-value">
                      {key === "zoom" ? `${crop.zoom.toFixed(2)}×` : `${Math.round(crop[key] * 100)}%`}
                    </span>
                  </span>
                  <input
                    aria-label={t(`player.${key}`)}
                    className="portrait-crop-dialog__range"
                    disabled={saving}
                    max={key === "zoom" ? 8 : 1}
                    min={key === "zoom" ? 1 : 0}
                    onChange={(event) => updateCrop({ ...crop, [key]: Number(event.target.value) })}
                    step={0.01}
                    type="range"
                    value={crop[key]}
                  />
                </label>
              ))}

              <div className="portrait-crop-dialog__toggle-row">
                <span>{t("player.individual")}</span>
                <Switch
                  aria-label={t("player.individual")}
                  checked={individual}
                  disabled={saving}
                  onChange={(event) => {
                    const enabled = event.target.checked;
                    const nextCrop = normalizePortraitCrop(
                      enabled ? crop : (editing.portrait_crop ?? defaultPortraitCrop),
                    );
                    setIndividual(enabled);
                    setCrop(nextCrop);
                    setEditing((value) => {
                      if (!value) return value;
                      return applyPortraitCrop(value, index, enabled, nextCrop);
                    });
                  }}
                />
              </div>
            </div>
          </div>

          {error ? <p role="alert">{error}</p> : null}
        </div>
      ) : null}
    </Dialog>
  );
}
