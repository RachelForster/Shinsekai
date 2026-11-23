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
import { EFFECT_RESOURCES_URL } from "./effectDraft";
import type { EffectPageContext } from "./effectContext";

interface EffectPageHeaderProps {
  ctx: EffectPageContext;
  navItems: PageSectionNavItem[];
}

export function EffectPageHeader({ ctx, navItems }: EffectPageHeaderProps) {
  const { t } = useI18n();
  const [importPickerOpen, setImportPickerOpen] = useState(false);

  return (
    <header className="page__header effect-page__header">
      <div className="effect-page__heading">
        <h1 className="page__title">{t("effect.title")}</h1>
      </div>
      <div className="page__actions effect-page__primary-actions">
        <div className="effect-page__resource-actions">
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(EFFECT_RESOURCES_URL)}
            variant="ghost"
          >
            {t("effect.action.community")}
          </Button>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal(EFFECT_RESOURCES_URL)}
            variant="ghost"
          >
            {t("effect.action.uploadContribution")}
          </Button>
        </div>
        <label className="effect-page__group-select">
          <span className="visually-hidden">{t("effect.groupListTitle")}</span>
          <Select
            disabled={ctx.isLoading || (!ctx.isCreating && !ctx.data.length)}
            onChange={(event) => ctx.selectEffect(event.target.value)}
            value={ctx.isCreating ? "" : ctx.selectedName || ctx.data[0]?.name || ""}
          >
            {ctx.isCreating ? <option value="">{t("common.new")}</option> : null}
            {!ctx.isCreating && !ctx.data.length ? <option value="">{t("effect.emptyTitle")}</option> : null}
            {ctx.data.map((effect) => (
              <option key={effect.name} value={effect.name}>
                {effect.name}
              </option>
            ))}
          </Select>
        </label>
        <div className="effect-page__package-actions">
          <Button
            className="button--header-icon"
            data-tooltip={t("common.new")}
            icon={<Plus aria-hidden className="button__icon" />}
            onClick={ctx.startCreatingEffect}
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
            onClick={ctx.exportCurrentEffect}
          >
            {t("common.export")}
          </AsyncButton>
          {ctx.inCreateMode ? (
            <>
              {ctx.isCreating && ctx.data.length > 0 ? (
                <Button
                  icon={<X aria-hidden className="button__icon" />}
                  onClick={ctx.cancelCreatingEffect}
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
              pendingIdentity={ctx.nameDirty}
              phase={ctx.autoSavePhase}
            />
          )}
        </div>
      </div>
      <PageSectionNav ariaLabel={t("effect.title")} items={navItems} />
      <PathPickerDialog
        acceptedExtensions={[".ef"]}
        multiple
        onClose={() => setImportPickerOpen(false)}
        onSelect={(path) => ctx.importEffects([path])}
        onSelectMany={(paths) => ctx.importEffects(paths)}
        open={importPickerOpen}
        title={t("common.import")}
      />
    </header>
  );
}
