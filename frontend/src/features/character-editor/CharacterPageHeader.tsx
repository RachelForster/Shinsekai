import { Download, ExternalLink, Plus, Save, Upload } from "lucide-react";

import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, FilePicker } from "../../shared/ui";
import { CHARACTER_RESOURCES_URL, importItemsLabel } from "./characterEditorUtils";

interface CharacterPageHeaderProps {
  exportPending: boolean;
  importPending: boolean;
  onCreate: () => void;
  onExport: () => void;
  onImport: () => void;
  onPendingImportItemsChange: (items: string[]) => void;
  onSave: () => void;
  pendingImportItems: string[];
  savePending: boolean;
}

export function CharacterPageHeader({
  exportPending,
  importPending,
  onCreate,
  onExport,
  onImport,
  onPendingImportItemsChange,
  onSave,
  pendingImportItems,
  savePending,
}: CharacterPageHeaderProps) {
  const { t } = useI18n();

  return (
    <header className="page__header">
      <div>
        <h1 className="page__title">{t("character.title")}</h1>
        <p className="page__description">{t("character.description")}</p>
      </div>
      <div className="page__actions">
        <Button icon={<Plus aria-hidden className="button__icon" />} onClick={onCreate}>
          {t("common.new")}
        </Button>
        <div className="page__file-picker">
          <FilePicker
            acceptedExtensions={[".char", ".cha"]}
            multiple
            onPathsChange={onPendingImportItemsChange}
            pickLabel={t("common.chooseFile")}
            pickerTitle={t("common.import")}
            placeholder={t("character.import.noFile")}
            readOnly
            value={pendingImportItems.length ? importItemsLabel(pendingImportItems) : ""}
          />
        </div>
        <AsyncButton
          disabled={!pendingImportItems.length}
          icon={<Upload aria-hidden className="button__icon" />}
          loading={importPending}
          onClick={onImport}
        >
          {t("common.import")}
        </AsyncButton>
        <AsyncButton
          icon={<Download aria-hidden className="button__icon" />}
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
    </header>
  );
}
