import { useId } from "react";
import { ChevronDown, Search } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, QueryErrorState, TextInput } from "../../shared/ui";
import { isKnowledgeLoading, type useKnowledgeController } from "./useKnowledgeController";

export function KnowledgeInstancePicker({
  controller: c,
  disabled = false,
}: {
  controller: ReturnType<typeof useKnowledgeController>;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const inputId = useId();
  const listId = useId();
  const catalogPages = Math.max(1, Math.ceil((c.catalog.data?.count ?? 0) / 20));
  const catalogLoading = c.catalog.isPending || isKnowledgeLoading(c.catalog.error);
  const catalogError = isKnowledgeLoading(c.catalog.error) ? null : c.catalog.error;
  return (
    <div className="knowledge-instance-picker">
      <label className="visually-hidden" htmlFor={inputId}>
        {t("knowledge.searchInstances")}
      </label>
      <div
        className="knowledge-picker"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) c.setInstancePickerOpen(false);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") c.setInstancePickerOpen(false);
        }}
      >
        <div className="knowledge-picker__input">
          <TextInput
            id={inputId}
            value={c.knowledgeQuery}
            disabled={disabled}
            role="combobox"
            aria-expanded={c.instancePickerOpen}
            aria-controls={listId}
            aria-autocomplete="list"
            placeholder={t("knowledge.queryPlaceholder")}
            onChange={(event) => c.changeKnowledgeQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                c.searchInstances();
              }
              if (event.key === "ArrowDown") {
                event.preventDefault();
                if (!c.instancePickerOpen) c.searchInstances();
                else document.getElementById(listId)?.querySelector<HTMLElement>('[role="option"]')?.focus();
              }
            }}
          />
          <AsyncButton
            aria-label={t("knowledge.searchInstances")}
            tooltip={t("knowledge.searchInstances")}
            disabled={disabled}
            loading={c.instancePickerOpen && c.catalog.isFetching}
            onClick={c.searchInstances}
            icon={<Search aria-hidden className="button__icon" />}
            variant="ghost"
          />
          <Button
            aria-label={t("knowledge.availableKnowledge")}
            aria-expanded={c.instancePickerOpen}
            aria-controls={listId}
            disabled={disabled}
            onClick={c.toggleInstances}
            icon={<ChevronDown aria-hidden className="button__icon" />}
            variant="ghost"
          />
        </div>
        {c.instancePickerOpen ? (
          <div className="knowledge-picker__dropdown">
            {catalogLoading ? (
              <p role="status" className="inline-status">
                {t("knowledge.loading")}
              </p>
            ) : null}
            {catalogError ? (
              <QueryErrorState
                error={catalogError}
                title={t("common.operationFailed")}
                body={t("knowledge.loadFailed")}
                retryLabel={t("common.retry")}
                onRetry={c.refresh}
              />
            ) : null}
            {!catalogLoading && !catalogError && !c.catalog.data?.knowledge.length ? (
              <p role="status">{t("knowledge.noInstances")}</p>
            ) : null}
            <div id={listId} role="listbox" aria-label={t("knowledge.availableKnowledge")}>
              {!catalogLoading && !catalogError
                ? c.catalog.data?.knowledge.map((knowledge) => (
                    <button
                      type="button"
                      className="knowledge-picker__option"
                      key={knowledge.knowledge_id}
                      role="option"
                      aria-selected={knowledge.knowledge_id === c.selectedKnowledge}
                      onClick={() => c.selectKnowledge(knowledge.knowledge_id)}
                      onKeyDown={(event) => {
                        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                          event.preventDefault();
                          const sibling =
                            event.key === "ArrowDown"
                              ? event.currentTarget.nextElementSibling
                              : event.currentTarget.previousElementSibling;
                          (sibling as HTMLElement | null)?.focus();
                        }
                      }}
                    >
                      <strong>{knowledge.knowledge_id}</strong>
                      <span>
                        {t("knowledge.instanceCounts", {
                          entries: knowledge.entryCount,
                          characters: knowledge.characterCount,
                        })}
                      </span>
                    </button>
                  ))
                : null}
            </div>
            {catalogPages > 1 ? (
              <div className="knowledge-pagination">
                <Button
                  disabled={c.catalogPage <= 1 || c.catalog.isFetching}
                  onClick={() => c.setCatalogPage(c.catalogPage - 1)}
                >
                  {t("knowledge.previous")}
                </Button>
                <span>{t("knowledge.page", { page: c.catalogPage, total: catalogPages })}</span>
                <Button
                  disabled={c.catalogPage >= catalogPages || c.catalog.isFetching}
                  onClick={() => c.setCatalogPage(c.catalogPage + 1)}
                >
                  {t("knowledge.next")}
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
