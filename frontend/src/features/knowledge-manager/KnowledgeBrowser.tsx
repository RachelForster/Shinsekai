import { RefreshCw, BookOpen, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import "./KnowledgeManagerPage.css";
import { useI18n } from "../../shared/i18n";
import { Button, AsyncButton, EmptyState, QueryErrorState, TextInput } from "../../shared/ui";
import { type useKnowledgeController } from "./useKnowledgeController";

export function KnowledgeBrowser({
  controller: c,
  embedded = false,
}: {
  controller: ReturnType<typeof useKnowledgeController>;
  embedded?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="knowledge-page__content">
      {c.selectedKnowledge ? (
        <>
          <div className="knowledge-browser__header">
            <strong>{c.selectedKnowledge}</strong>
            <div className="page__actions">
              <Button
                disabled={c.isFetching}
                onClick={c.refresh}
                variant="ghost"
                icon={<RefreshCw aria-hidden className="button__icon" />}
              >
                {t("knowledge.refresh")}
              </Button>
            </div>
          </div>
        </>
      ) : null}
      <KnowledgeEntriesSection controller={c} embedded={embedded} />
    </div>
  );
}

function KnowledgeEntriesSection({
  controller: c,
  embedded = false,
}: {
  controller: ReturnType<typeof useKnowledgeController>;
  embedded?: boolean;
}) {
  const { t } = useI18n();
  const v = c.entriesView;
  const hasRows = c.memories.length > 0;
  const Heading = embedded ? "h3" : "h2";
  return (
    <section
      id="knowledge-entries"
      className={embedded ? "knowledge-section__group" : "section page-section-anchor"}
      aria-labelledby="knowledge-entries-title"
    >
      <div className="section__header">
        <Heading id="knowledge-entries-title" className="section__title">
          {t("knowledge.information")}
        </Heading>
      </div>
      {!c.selectedKnowledge ? (
        <EmptyState title={t("knowledge.selectKnowledge")} body={t("knowledge.selectKnowledgeHint")} />
      ) : (
        <>
          <div className="knowledge-search-row">
            <TextInput
              className="knowledge-search-row__input"
              aria-label={t("knowledge.searchEntries")}
              value={c.searchInput}
              onChange={(event) => c.setSearchInput(event.target.value)}
              placeholder={t("knowledge.searchEntriesHint")}
              onKeyDown={(event) => {
                if (event.key === "Enter") c.searchEntries();
              }}
            />
            <AsyncButton
              disabled={!c.searchInput.trim()}
              loading={v.isFetching}
              onClick={c.searchEntries}
              icon={<Search aria-hidden className="button__icon" />}
            >
              {t("knowledge.search")}
            </AsyncButton>
            <Button
              disabled={!c.searchTerm}
              onClick={c.clearSearch}
              variant="ghost"
              icon={<X aria-hidden className="button__icon" />}
            >
              {t("knowledge.clearSearch")}
            </Button>
          </div>
          {c.searchTerm ? (
            <p className="inline-status" role="status">
              {t("knowledge.searchResults", { count: c.searchCount, query: c.searchTerm })}
            </p>
          ) : null}
          {v.isLoading ? (
            <EmptyState title={t("knowledge.loading")} />
          ) : v.error ? (
            <QueryErrorState
              error={v.error}
              title={t("common.operationFailed")}
              body={t("knowledge.loadFailed")}
              onRetry={c.refresh}
              retryLabel={t("common.retry")}
            />
          ) : !hasRows ? (
            <EmptyState
              title={t(c.searchTerm ? "knowledge.noSearchResults" : "knowledge.emptyTitle")}
              body={!c.searchTerm ? t("knowledge.emptyBody") : undefined}
            />
          ) : (
            <div className="knowledge-table knowledge-browser__rows">
              {c.memories.map((entry) => (
                <div className="knowledge-row" key={entry.id || entry.memory}>
                  <BookOpen aria-hidden className="knowledge-row__icon" />
                  <div className="knowledge-row__content">
                    <strong>{entry.memory}</strong>
                    <span>{entry.id}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
          {!v.isLoading && !v.error && (hasRows || v.page > 1) ? (
            <div className="knowledge-pagination" aria-label={t("knowledge.pagination")}>
              <Button
                disabled={v.page <= 1 || v.isFetching}
                onClick={v.previous}
                aria-label={t("knowledge.previous")}
                icon={<ChevronLeft aria-hidden className="button__icon" />}
                variant="ghost"
              />
              <span className="inline-status">{t("knowledge.page", { page: v.page, total: v.totalPages })}</span>
              <Button
                disabled={!v.hasNext || v.isFetching}
                onClick={v.next}
                aria-label={t("knowledge.next")}
                icon={<ChevronRight aria-hidden className="button__icon" />}
                variant="ghost"
              />
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
