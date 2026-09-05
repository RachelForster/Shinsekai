import { useEffect, useMemo, useState } from "react";
import { Check, Star } from "lucide-react";

import type { Character } from "../../shared/platform/types";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Dialog } from "../../shared/ui";
import { getCharacterChipStyle } from "./templateFlow";
import "./PrimaryCharacterDialog.css";

interface PrimaryCharacterDialogProps {
  characters: Character[];
  initialPrimaryCharacters?: string[];
  onConfirm: (primaryCharacters: string[]) => void;
  onUseAll: () => void;
  open: boolean;
  pending?: boolean;
}

const EMPTY_PRIMARY_CHARACTER_NAMES: string[] = [];

export function PrimaryCharacterDialog({
  characters,
  initialPrimaryCharacters = EMPTY_PRIMARY_CHARACTER_NAMES,
  onConfirm,
  onUseAll,
  open,
  pending = false,
}: PrimaryCharacterDialogProps) {
  const { t } = useI18n();
  const availableNames = useMemo(() => new Set(characters.map((character) => character.name)), [characters]);
  const [primaryNames, setPrimaryNames] = useState<string[]>([]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const restored = initialPrimaryCharacters.filter((name) => availableNames.has(name));
    setPrimaryNames(restored.length ? restored : characters[0] ? [characters[0].name] : []);
  }, [availableNames, characters, initialPrimaryCharacters, open]);

  const selected = new Set(primaryNames);
  const toggle = (name: string) => {
    setPrimaryNames((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    );
  };

  return (
    <Dialog
      bodyClassName="primary-character-dialog__body"
      className="primary-character-dialog"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button disabled={pending} onClick={onUseAll}>
            {t("template.primaryCharacters.useAll")}
          </Button>
          <AsyncButton
            disabled={!primaryNames.length}
            icon={<Check aria-hidden className="button__icon" />}
            loading={pending}
            onClick={() => onConfirm(primaryNames)}
            variant="primary"
          >
            {t("template.primaryCharacters.confirm")}
          </AsyncButton>
        </>
      }
      onClose={onUseAll}
      open={open}
      title={t("template.primaryCharacters.title")}
    >
      <p className="primary-character-dialog__description">
        {t("template.primaryCharacters.description", { count: characters.length })}
      </p>
      <p className="primary-character-dialog__count">
        {t("template.primaryCharacters.count", { count: primaryNames.length, total: characters.length })}
      </p>
      <div className="primary-character-dialog__grid">
        {characters.map((character) => {
          const isPrimary = selected.has(character.name);
          const hasBrief = Boolean(character.character_brief?.trim());
          return (
            <button
              aria-pressed={isPrimary}
              className={`primary-character-dialog__card${isPrimary ? " primary-character-dialog__card--selected" : ""}`}
              disabled={pending}
              key={character.name}
              onClick={() => toggle(character.name)}
              style={getCharacterChipStyle(character.color || "")}
              type="button"
            >
              <span className="primary-character-dialog__name">
                <Star aria-hidden className="primary-character-dialog__star" />
                {character.name}
              </span>
              <span className="primary-character-dialog__status">
                {isPrimary
                  ? t("template.primaryCharacters.primary")
                  : hasBrief
                    ? t("template.primaryCharacters.hasBrief")
                    : t("template.primaryCharacters.needsBrief")}
              </span>
            </button>
          );
        })}
      </div>
    </Dialog>
  );
}
