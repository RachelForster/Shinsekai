import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { charactersQueryKey, saveCharacter } from "../../entities/character/repository";
import { applyPortraitCrop } from "../../shared/components/Portrait";
import { PortraitCropDialog } from "../../shared/components/PortraitCropDialog";
import { useI18n } from "../../shared/i18n";
import { getCharacterDisplayName } from "../../shared/playerCharacterOptions";
import type { Character } from "../../shared/platform/types";
import { Button, Dialog, Select, Switch } from "../../shared/ui";

export { applyPortraitCrop };

export function PlayerCharacterSettings({
  characters,
  selected,
  onSelect,
  readSpeech,
  onReadSpeech,
  allowDialogue,
  onAllowDialogue,
  open,
  onClose,
}: {
  characters: Character[];
  selected: string;
  onSelect: (name: string) => void;
  readSpeech: boolean;
  onReadSpeech: (enabled: boolean) => void;
  allowDialogue: boolean;
  onAllowDialogue: (enabled: boolean) => void;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [cropOpen, setCropOpen] = useState(false);
  const queryClient = useQueryClient();
  const character = characters.find((item) => item.name === selected);
  const save = useMutation({
    mutationFn: (nextCharacter: Character) => saveCharacter(nextCharacter, nextCharacter.name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setCropOpen(false);
    },
  });

  return (
    <>
      <Dialog
        closeLabel={t("common.close")}
        footer={
          <Button onClick={onClose} variant="primary">
            {t("common.confirm")}
          </Button>
        }
        onClose={onClose}
        open={open}
        title={t("player.select")}
      >
        <div className="template-mobile-access">
          <label style={{ display: "grid", gap: 8 }}>
            {t("player.select")}
            <Select
              aria-label={t("player.select")}
              onChange={(event) => onSelect(event.target.value)}
              value={character ? selected : ""}
            >
              <option value="">{t("player.none")}</option>
              {characters.map((item) => (
                <option key={item.name} value={item.name}>
                  {getCharacterDisplayName(item)}
                </option>
              ))}
            </Select>
          </label>
          {character ? (
            <>
              <p>{t("player.hint")}</p>
              <label className="template-toggle-row">
                <span>{t("player.allowDialogue")}</span>
                <Switch checked={allowDialogue} onChange={(event) => onAllowDialogue(event.target.checked)} />
              </label>
              <p>{t("player.allowDialogueHint")}</p>
              <label className="template-toggle-row">
                <span>{t("player.readSpeech")}</span>
                <Switch checked={readSpeech} onChange={(event) => onReadSpeech(event.target.checked)} />
              </label>
              <p>{t("player.speechHint")}</p>
              <Button
                disabled={!character.sprites.length}
                onClick={() => {
                  save.reset();
                  setCropOpen(true);
                }}
              >
                {t("player.adjust")}
              </Button>
            </>
          ) : null}
        </div>
      </Dialog>

      <PortraitCropDialog
        character={character ?? null}
        error={save.isError ? String(save.error) : undefined}
        onClose={() => setCropOpen(false)}
        onSave={(nextCharacter) => save.mutate(nextCharacter)}
        open={cropOpen}
        saving={save.isPending}
        title={t("player.adjust")}
      />
    </>
  );
}
