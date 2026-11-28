import { Save } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { PluginSlot } from "../../shared/plugin/PluginSlot";
import { AsyncButton, EmptyState, QueryErrorState, Select, TextInput } from "../../shared/ui";
import type { TemplateEditorContext } from "./templateContext";

interface TemplatePageHeaderProps {
  ctx: TemplateEditorContext;
}

export function TemplatePageHeader({ ctx }: TemplatePageHeaderProps) {
  const { t } = useI18n();

  return (
    <>
      <header className="template-page__topbar">
        <label className="template-topbar-field template-topbar-field--select">
          <span className="template-topbar-field__label">{t("template.section.load")}</span>
          <Select
            disabled={!ctx.templates.length}
            onChange={(event) => ctx.handleTemplateSelect(event.target.value)}
            value={ctx.templateSelectValue}
          >
            <option value="">
              {ctx.sessionDraftActive || ctx.isCreating
                ? ctx.draft.name || t("template.defaultName")
                : t("template.section.load")}
            </option>
            {ctx.templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="template-topbar-field">
          <span className="template-topbar-field__label">{t("template.field.templateName")}</span>
          <span className="input-group">
            <TextInput
              className={ctx.nameError ? "input--error" : ""}
              onChange={(event) => {
                ctx.updateDraft({ name: event.target.value });
                if (event.target.value.trim()) {
                  ctx.setNameError("");
                }
              }}
              value={ctx.draft.name}
            />
            {!ctx.conversationId && (
              <AsyncButton
                className="template-save-button"
                icon={<Save aria-hidden className="button__icon" />}
                loading={ctx.savePending}
                onClick={ctx.saveTemplate}
              >
                {t("common.save")}
              </AsyncButton>
            )}
            <PluginSlot
              context={{
                entityId: ctx.templateSelectValue || ctx.draft.id || undefined,
                entityType: "template",
                page: "template",
              }}
              maxInline={2}
              slot="template-header-actions"
            />
          </span>
          {ctx.nameError ? <span className="field-error">{ctx.nameError}</span> : null}
        </label>
      </header>

      {ctx.isLoading || ctx.failedQuery || (!ctx.templates.length && !ctx.failedQuery) ? (
        <div className="template-page__status">
          {ctx.isLoading ? <EmptyState title={t("template.loading")} /> : null}
          {ctx.failedQuery ? (
            <QueryErrorState
              error={ctx.failedQuery.error}
              onRetry={() => void ctx.failedQuery?.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!ctx.isLoading && !ctx.failedQuery && !ctx.templates.length ? (
            <EmptyState body={t("template.emptyBody")} title={t("template.emptyTitle")} />
          ) : null}
        </div>
      ) : null}
    </>
  );
}
