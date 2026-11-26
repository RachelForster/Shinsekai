import { useState } from "react";
import { ExternalLink, FolderInput, FolderOutput, Plus, Save, X } from "lucide-react";

import { openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import {
  AsyncButton,
  AutoSaveStatus,
  Button,
  PageSectionNav,
  PathPickerDialog,
  Select,
  type PageSectionNavItem,
} from "../../shared/ui";
import { BACKGROUND_RESOURCES_URL, type BackgroundPageContext } from "./backgroundContext";

interface BackgroundPageHeaderProps {
  ctx: BackgroundPageContext;
  navItems: PageSectionNavItem[];
}

export function BackgroundPageHeader({ ctx, navItems }: BackgroundPageHeaderProps) {
  const { t } = useI18n();
  const [importPickerOpen, setImportPickerOpen] = useState(false);

  return (
    <header className="page__header background-page__header">
      <div className="background-page__heading">
        <h1 className="page__title">{t("background.title")}</h1>
      </div>
      <div className="page__actions background-page__primary-actions">
        <div className="background-page__resource-actions">
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(BACKGROUND_RESOURCES_URL)}
            variant="ghost"
          >
            {t("background.action.community")}
          </Button>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(BACKGROUND_RESOURCES_URL)}
            variant="ghost"
          >
            {t("background.action.uploadContribution")}
          </Button>
        </div>
        <label className="background-page__group-select">
          <span className="visually-hidden">{t("background.groupListTitle")}</span>
          <Select
            disabled={ctx.isLoading || (!ctx.isCreating && !ctx.data.length)}
            onChange={(event) => ctx.selectBackground(event.target.value)}
            value={ctx.isCreating ? "" : ctx.selectedName || ctx.data[0]?.name || ""}
          >
            {ctx.isCreating ? <option value="">{t("common.new")}</option> : null}
            {!ctx.isCreating && !ctx.data.length ? <option value="">{t("background.emptyTitle")}</option> : null}
            {ctx.data.map((background) => (
              <option key={background.name} value={background.name}>
                {background.name}
              </option>
            ))}
          </Select>
        </label>
        <div className="background-page__package-actions">
          <Button
            className="button--header-icon"
            data-tooltip={t("common.new")}
            icon={<Plus aria-hidden className="button__icon" />}
            onClick={ctx.startCreatingBackground}
          >
            {t("common.new")}
          </Button>
          <AsyncButton
            className="button--header-icon"
            data-tooltip={t("common.import")}
            icon={<FolderInput aria-hidden className="button__icon" />}
            loading={ctx.importPending}
            onClick={() => setImportPickerOpen(true)}
          >
            {t("common.import")}
          </AsyncButton>
          <AsyncButton
            className="button--header-icon"
            data-tooltip={t("common.export")}
            icon={<FolderOutput aria-hidden className="button__icon" />}
            loading={ctx.exportPending}
            onClick={ctx.exportCurrentBackground}
          >
            {t("common.export")}
          </AsyncButton>
          {ctx.inCreateMode ? (
            <>
              {ctx.isCreating && ctx.data.length > 0 ? (
                <Button
                  icon={<X aria-hidden className="button__icon" />}
                  onClick={ctx.cancelCreatingBackground}
                  variant="ghost"
                >
                  {t("common.cancel")}
                </Button>
              ) : null}
              <AsyncButton
                icon={<Save aria-hidden className="button__icon" />}
                loading={ctx.savePending}
                onClick={ctx.saveDraft}
                variant="primary"
              >
                {t("common.create")}
              </AsyncButton>
            </>
          ) : (
            <AutoSaveStatus
              errorMessage={ctx.autoSaveError}
              onRetry={ctx.autoSaveRetry}
              pendingIdentity={ctx.nameDirty || ctx.spritePrefixDirty}
              phase={ctx.autoSavePhase}
            />
          )}
        </div>
      </div>
      <PageSectionNav ariaLabel={t("background.title")} items={navItems} />
      <PathPickerDialog
        acceptedExtensions={[".bg"]}
        multiple
        onClose={() => setImportPickerOpen(false)}
        onSelect={(path) => ctx.importBackgrounds([path])}
        onSelectMany={(paths) => ctx.importBackgrounds(paths)}
        open={importPickerOpen}
        title={t("common.import")}
      />
    </header>
  );
}
