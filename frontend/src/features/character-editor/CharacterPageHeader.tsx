import { useState } from "react";
import type { ReactNode } from "react";
import { ExternalLink, FolderInput, FolderOutput, Plus, Save } from "lucide-react";

import type { Character } from "../../entities/config/types";
import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { getCharacterDisplayName } from "../../shared/playerCharacterOptions";
import { AsyncButton, Button, PathPickerDialog, Select } from "../../shared/ui";
import { CHARACTER_RESOURCES_URL, isSelfPersonaCharacter } from "./characterEditorUtils";

interface CharacterPageHeaderProps {
  characters: Character[];
  exportPending: boolean;
  importPending: boolean;
  isCreating: boolean;
  isLoading: boolean;
  onCreate: () => void;
  onExport: () => void;
  onImport: (items: string[]) => void;
  onSave: () => void;
  onSelectCharacter: (name: string) => void;
  savePending: boolean;
  sectionNav?: ReactNode;
  selectedName: string;
}

export function CharacterPageHeader({
  characters,
  exportPending,
  importPending,
  isCreating,
  isLoading,
  onCreate,
  onExport,
  onImport,
  onSave,
  onSelectCharacter,
  savePending,
  sectionNav,
  selectedName,
}: CharacterPageHeaderProps) {
  const { t } = useI18n();
  const [importPickerOpen, setImportPickerOpen] = useState(false);
  const currentValue = isCreating ? "" : selectedName || characters[0]?.name || "";
  const activeCharacter = isCreating ? undefined : characters.find((item) => item.name === currentValue);

  return (
    <header className="page__header character-page__header">
      <div className="character-page__heading">
        <h1 className="page__title">{t("character.title")}</h1>
      </div>
      <div className="page__actions character-page__toolbar" aria-label={t("character.title")}>
        <div className="character-page__toolbar-group character-page__toolbar-group--links">
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(CHARACTER_RESOURCES_URL)}
            variant="ghost"
          >
            {t("character.action.community")}
          </Button>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(CHARACTER_RESOURCES_URL)}
            variant="ghost"
          >
            {t("character.action.uploadContribution")}
          </Button>
        </div>
        <label className="character-page__select">
          <span className="visually-hidden">{t("character.row.current")}</span>
          <Select
            aria-label={t("character.row.current")}
            disabled={isLoading || !characters.length}
            onChange={(event) => onSelectCharacter(event.target.value)}
            value={currentValue}
          >
            {isCreating ? <option value="">{t("common.new")}</option> : null}
            {characters.map((character) => (
              <option key={character.name} value={character.name}>
                {getCharacterDisplayName(character)}
              </option>
            ))}
          </Select>
        </label>
        {isSelfPersonaCharacter(activeCharacter) ? (
          <span className="character-builtin-badge">{t("character.selfPersona.badge")}</span>
        ) : null}
        <div className="character-page__toolbar-group character-page__toolbar-group--primary">
          <Button
            className="button--header-icon"
            data-tooltip={t("common.new")}
            icon={<Plus aria-hidden className="button__icon" />}
            onClick={onCreate}
          >
            {t("common.new")}
          </Button>
          <AsyncButton
            className="button--header-icon"
            data-tooltip={t("common.import")}
            icon={<FolderInput aria-hidden className="button__icon" />}
            loading={importPending}
            onClick={() => setImportPickerOpen(true)}
          >
            {t("common.import")}
          </AsyncButton>
          <AsyncButton
            className="button--header-icon"
            data-tooltip={t("common.export")}
            icon={<FolderOutput aria-hidden className="button__icon" />}
            loading={exportPending}
            onClick={onExport}
          >
            {t("common.export")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={savePending}
            onClick={onSave}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
        </div>
      </div>
      {sectionNav}
      <PathPickerDialog
        acceptedExtensions={[".char", ".cha"]}
        multiple
        onClose={() => setImportPickerOpen(false)}
        onSelect={(path) => onImport([path])}
        onSelectMany={onImport}
        open={importPickerOpen}
        title={t("common.import")}
      />
    </header>
  );
}
