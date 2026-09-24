import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { charactersQueryKey, saveCharacter } from "../../entities/character/repository";
import type { Character, PortraitCrop } from "../../shared/platform/types";
import { Portrait, defaultPortraitCrop, portraitGeometry } from "../../shared/components/Portrait";
import { Button, Dialog, Select, Switch } from "../../shared/ui";
import { useI18n } from "../../shared/i18n";

export function applyPortraitCrop(
  character: Character,
  spriteIndex: number,
  individual: boolean,
  crop: PortraitCrop,
): Character {
  const next = structuredClone(character);
  if (!next.sprites[spriteIndex]) return next;
  if (individual) next.sprites[spriteIndex].portrait_crop = crop;
  else {
    next.portrait_crop = crop;
    next.sprites[spriteIndex].portrait_crop = null;
  }
  return next;
}

export function PlayerCharacterSettings({
  characters,
  selected,
  onSelect,
  readSpeech,
  onReadSpeech,
  open,
  onClose,
}: {
  characters: Character[];
  selected: string;
  onSelect: (name: string) => void;
  readSpeech: boolean;
  onReadSpeech: (enabled: boolean) => void;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<Character | null>(null);
  const [index, setIndex] = useState(0);
  const [individual, setIndividual] = useState(false);
  const [crop, setCrop] = useState<PortraitCrop>(defaultPortraitCrop);
  const image = useRef({ width: 1, height: 1 });
  const drag = useRef<{ x: number; y: number; crop: PortraitCrop } | null>(null);
  const queryClient = useQueryClient();
  const character = characters.find((item) => item.name === selected);
  const save = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error("No character selected");
      return saveCharacter(editing, editing.name);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setEditing(null);
    },
  });
  const selectSprite = (nextIndex: number, value: Character) => {
    setIndex(nextIndex);
    const override = value.sprites[nextIndex]?.portrait_crop;
    setIndividual(Boolean(override));
    setCrop(override ?? value.portrait_crop ?? defaultPortraitCrop);
    drag.current = null;
  };
  const updateCrop = (nextCrop: PortraitCrop) => {
    setCrop(nextCrop);
    setEditing((value) => {
      if (!value) return value;
      return applyPortraitCrop(value, index, individual, nextCrop);
    });
  };
  return (
    <>
      <Dialog open={open} onClose={onClose} title={t("player.select")}>
        <div className="template-mobile-access">
          <label style={{ display: "grid", gap: 8 }}>
            {t("player.select")}
            <Select
              aria-label={t("player.select")}
              value={character ? selected : ""}
              onChange={(event) => onSelect(event.target.value)}
            >
              <option value="">{t("player.none")}</option>
              {characters.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </Select>
          </label>
          {character ? (
            <>
              <p>{t("player.hint")}</p>
              <label className="template-toggle-row">
                <span>{t("player.readSpeech")}</span>
                <Switch checked={readSpeech} onChange={(event) => onReadSpeech(event.target.checked)} />
              </label>
              <p>{t("player.speechHint")}</p>
              <Button
                disabled={!character.sprites.length}
                onClick={() => {
                  save.reset();
                  const next = structuredClone(character);
                  setEditing(next);
                  selectSprite(0, next);
                }}
              >
                {t("player.adjust")}
              </Button>
            </>
          ) : null}
        </div>
      </Dialog>
      <Dialog
        open={Boolean(editing)}
        onClose={() => {
          if (!save.isPending) setEditing(null);
        }}
        title={t("player.adjust")}
        footer={
          <>
            <Button disabled={save.isPending} onClick={() => updateCrop({ ...defaultPortraitCrop })}>
              {t("player.reset")}
            </Button>
            <Button disabled={save.isPending} onClick={() => save.mutate()}>
              {t("common.save")}
            </Button>
          </>
        }
      >
        {editing?.sprites[index] ? (
          <div style={{ display: "grid", gap: 16 }}>
            <Select
              aria-label={t("player.sprite")}
              disabled={save.isPending}
              value={index}
              onChange={(event) => selectSprite(Number(event.target.value), editing)}
            >
              {editing.sprites.map((sprite, i) => (
                <option key={`${sprite.path}-${i}`} value={i}>
                  {i + 1} · {sprite.path.split(/[\\/]/).pop()}
                </option>
              ))}
            </Select>
            <p>{t("player.dragHint")}</p>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 16 }}>
              <Portrait
                name={editing.name}
                path={editing.sprites[index].path}
                crop={crop}
                size={200}
                onImageSize={(width, height) => {
                  image.current = { width, height };
                }}
                onPointerDown={(event) => {
                  if (save.isPending) return;
                  event.currentTarget.setPointerCapture(event.pointerId);
                  drag.current = { x: event.clientX, y: event.clientY, crop };
                }}
                onPointerMove={(event) => {
                  const start = drag.current;
                  if (!start || !event.buttons || save.isPending) return;
                  const { width, height } = image.current;
                  const side = portraitGeometry(width, height, start.crop).side;
                  const scale = event.currentTarget.clientWidth / side;
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
              />
              <div style={{ display: "grid", gap: 16, flex: 1, minWidth: 160 }}>
                {(["x", "y", "zoom"] as const).map((key) => (
                  <label key={key} style={{ display: "grid", gap: 4 }}>
                    {t(`player.${key}`)}
                    <input
                      type="range"
                      style={{ accentColor: "var(--color-accent-primary)" }}
                      disabled={save.isPending}
                      min={key === "zoom" ? 1 : 0}
                      max={key === "zoom" ? 8 : 1}
                      step={0.01}
                      value={crop[key]}
                      onChange={(event) => updateCrop({ ...crop, [key]: Number(event.target.value) })}
                    />
                  </label>
                ))}
                <label className="template-toggle-row">
                  <span>{t("player.individual")}</span>
                  <Switch
                    disabled={save.isPending}
                    checked={individual}
                    onChange={(event) => {
                      const enabled = event.target.checked;
                      const nextCrop = enabled ? crop : (editing.portrait_crop ?? defaultPortraitCrop);
                      setIndividual(enabled);
                      setCrop(nextCrop);
                      setEditing((value) => {
                        if (!value) return value;
                        return applyPortraitCrop(value, index, enabled, nextCrop);
                      });
                    }}
                  />
                </label>
              </div>
            </div>
            {save.isError ? <p role="alert">{String(save.error)}</p> : null}
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
