import { useState } from "react";
import type { ReactNode } from "react";
import { ExternalLink, FolderInput, FolderOutput, Plus, Save, X } from "lucide-react";

import type { Character } from "../../entities/config/types";
import { openExternal } from "../../entities/files/repository";
import type { AutoSavePhase } from "../../shared/hooks/useDebouncedAutoSave";
import { useI18n } from "../../shared/i18n";
import { getCharacterDisplayName } from "../../shared/playerCharacterOptions";
import { PluginSlot } from "../../shared/plugin/PluginSlot";
import { AsyncButton, AutoSaveStatus, Button, PathPickerDialog, Select } from "../../shared/ui";
import { CHARACTER_RESOURCES_URL, isSelfPersonaCharacter } from "./characterEditorUtils";

interface CharacterPageHeaderProps {
  autoSaveError?: string;
  autoSavePhase?: AutoSavePhase;
  canCancelCreate?: boolean;
  characters: Character[];
  exportPending: boolean;
  importPending: boolean;
  isCreating: boolean;
  isLoading: boolean;
  onCancelCreate?: () => void;
  onCreate: () => void;
  onExport: () => void;
  onImport: (items: string[]) => void;
  onRetryAutoSave?: () => void;
  onSave: () => void;
  onSelectCharacter: (name: string) => void;
  pendingIdentity?: boolean;
  savePending: boolean;
  sectionNav?: ReactNode;
  selectedName: string;
}

export function CharacterPageHeader({
  autoSaveError,
  autoSavePhase = "idle",
  canCancelCreate = false,
  characters,
  exportPending,
  importPending,
  isCreating,
  isLoading,
  onCancelCreate,
  onCreate,
  onExport,
  onImport,
  onRetryAutoSave,
  onSave,
  onSelectCharacter,
  pendingIdentity = false,
  savePending,
  sectionNav,
  selectedName,
}: CharacterPageHeaderProps) {
  const { t } = useI18n();
  const [importPickerOpen, setImportPickerOpen] = useState(false);
  const showCreateControls = isCreating || characters.length === 0;
  const currentValue = showCreateControls ? "" : selectedName || characters[0]?.name || "";
  const activeCharacter = showCreateControls ? undefined : characters.find((item) => item.name === currentValue);

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
            {showCreateControls ? <option value="">{t("common.new")}</option> : null}
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
          <PluginSlot
            context={{ entityId: currentValue || undefined, entityType: "character", page: "character" }}
            maxInline={2}
            slot="character-header-actions"
          />
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
          {showCreateControls ? (
            <>
              {canCancelCreate && onCancelCreate ? (
                <Button icon={<X aria-hidden className="button__icon" />} onClick={onCancelCreate} variant="ghost">
                  {t("common.cancel")}
                </Button>
              ) : null}
              <AsyncButton
                icon={<Save aria-hidden className="button__icon" />}
                loading={savePending}
                onClick={onSave}
                variant="primary"
              >
                {t("common.create")}
              </AsyncButton>
            </>
          ) : (
            <AutoSaveStatus
              errorMessage={autoSaveError}
              onRetry={onRetryAutoSave}
              pendingIdentity={pendingIdentity}
              phase={autoSavePhase}
            />
          )}
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
