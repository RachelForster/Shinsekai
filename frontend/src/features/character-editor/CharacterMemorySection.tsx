import { Brain, ChevronLeft, ChevronRight, Download, RefreshCw, Search, X } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { CharacterMemoryList } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, QueryErrorState, TextInput } from "../../shared/ui";

interface CharacterMemorySectionProps {
  addPending: boolean;
  data?: CharacterMemoryList;
  deletePending: boolean;
  depError?: { kind: string; moduleName: string; packageName: string } | null;
  depInstalling: boolean;
  error: unknown;
  id?: string;
  isChecking: boolean;
  isError: boolean;
  isFetching: boolean;
  isFetched: boolean;
  isLoading: boolean;
  memoryInput: string;
  memoryName: string;
  memoryPage: number;
  memoryTotalPages: number;
  activeSearchQuery: string;
  onAddMemory: () => void;
  onClearSearch: () => void;
  onDeleteMemory: (memory: { id: string; memory: string }) => void;
  onInstallDep: () => void;
  onMemoryInputChange: (value: string) => void;
  onMemoryPageChange: (updater: (page: number) => number) => void;
  onRefresh: () => void;
  onSearch: () => void;
  onSearchInputChange: (value: string) => void;
  searchInput: string;
  searchPending: boolean;
}

export function CharacterMemorySection({
  addPending,
  data,
  deletePending,
  depError,
  depInstalling,
  error,
  id,
  isChecking,
  isError,
  isFetched,
  isFetching,
  isLoading,
  memoryInput,
  memoryName,
  memoryPage,
  memoryTotalPages,
  activeSearchQuery,
  onAddMemory,
  onClearSearch,
  onDeleteMemory,
  onInstallDep,
  onMemoryInputChange,
  onMemoryPageChange,
  onRefresh,
  onSearch,
  onSearchInputChange,
  searchInput,
  searchPending,
}: CharacterMemorySectionProps) {
  const { t } = useI18n();
  const hasMemoryRows = Boolean(data?.memories.length);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.memory.section")}</h2>
        <div className="page__actions">
          <span className="entity-list__meta">{data ? t("character.memory.count", { count: data.count }) : ""}</span>
          <Button
            disabled={!memoryName || isFetching || depInstalling || isChecking}
            icon={<RefreshCw aria-hidden className="button__icon" />}
            onClick={onRefresh}
            variant="ghost"
          >
            {isChecking ? t("character.memory.initializing") : t("character.memory.refresh")}
          </Button>
        </div>
      </div>
      {!depError ? (
        <div className="memory-search-row">
          <label className="memory-search-row__input">
            <TextInput
              aria-label={t("character.memory.search")}
              disabled={!memoryName || isChecking}
              onChange={(event) => onSearchInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  onSearch();
                }
              }}
              placeholder={t("character.memory.searchPlaceholder")}
              value={searchInput}
            />
          </label>
          <AsyncButton
            disabled={!memoryName || !searchInput.trim() || isChecking}
            icon={<Search aria-hidden className="button__icon" />}
            loading={searchPending}
            onClick={onSearch}
          >
            {t("character.memory.search")}
          </AsyncButton>
          <Button
            disabled={!activeSearchQuery}
            icon={<X aria-hidden className="button__icon" />}
            onClick={onClearSearch}
            variant="ghost"
          >
            {t("character.memory.clearSearch")}
          </Button>
        </div>
      ) : null}
      {activeSearchQuery ? (
        <p className="inline-status memory-search-row__status">
          {t("character.memory.searchResult", { count: data?.count ?? 0, query: activeSearchQuery })}
        </p>
      ) : null}
      {!memoryName ? <EmptyState title={t("character.memory.nameRequired")} /> : null}
      {memoryName && isChecking ? <EmptyState title={t("character.memory.initializing")} /> : null}
      {memoryName && depError ? (
        <div className="empty-state" role="status">
          <div className="empty-state__icon">
            <Download aria-hidden size={32} />
          </div>
          <p className="empty-state__title">{t("character.memory.depMissingTitle")}</p>
          <p className="empty-state__body">{t("character.memory.depMissingBody")}</p>
          <div className="empty-state__actions">
            <AsyncButton loading={depInstalling} onClick={onInstallDep} variant="primary">
              {depInstalling ? t("character.memory.depInstalling") : t("character.memory.depMissingInstall")}
            </AsyncButton>
          </div>
        </div>
      ) : null}
      {memoryName && isLoading ? <EmptyState title={t("character.memory.loading")} /> : null}
      {memoryName && isError && !depError ? (
        <QueryErrorState
          body={t("character.memory.error")}
          error={error}
          onRetry={onRefresh}
          retryLabel={t("common.retry")}
          title={t("common.operationFailed")}
        />
      ) : null}
      {memoryName && isFetched && !isLoading && !isError && !depError && !data?.memories.length ? (
        <EmptyState title={activeSearchQuery ? t("character.memory.searchEmpty") : t("character.memory.empty")} />
      ) : null}
      {hasMemoryRows ? (
        <div className="memory-table">
          {data?.memories.map((memory) => (
            <div className="memory-row" key={memory.id || memory.memory}>
              <Brain aria-hidden className="asset-row__icon" />
              <div className="memory-row__content">
                <strong>{memory.memory}</strong>
                <span>{memory.id}</span>
              </div>
              <AsyncButton
                disabled={!memory.id}
                loading={deletePending}
                onClick={() => {
                  if (!memory.id) {
                    return;
                  }
                  onDeleteMemory({ id: memory.id, memory: memory.memory });
                }}
                variant="ghost"
              >
                {t("character.memory.delete")}
              </AsyncButton>
            </div>
          ))}
        </div>
      ) : null}
      {hasMemoryRows ? (
        <div className="memory-pagination" aria-label={t("character.memory.pagination")}>
          <Button
            disabled={memoryPage <= 1}
            icon={<ChevronLeft aria-hidden className="button__icon" />}
            onClick={() => onMemoryPageChange((page) => Math.max(1, page - 1))}
            tooltip={t("character.memory.previous")}
            variant="ghost"
          />
          <span className="inline-status">
            {t("character.memory.page", { page: memoryPage, total: memoryTotalPages })}
          </span>
          <Button
            disabled={memoryPage >= memoryTotalPages}
            icon={<ChevronRight aria-hidden className="button__icon" />}
            onClick={() => onMemoryPageChange((page) => Math.min(memoryTotalPages, page + 1))}
            tooltip={t("character.memory.next")}
            variant="ghost"
          />
        </div>
      ) : null}
      {!depError ? (
        <div className="memory-add-row">
          <TextInput
            disabled={!memoryName}
            onChange={(event) => onMemoryInputChange(event.target.value)}
            placeholder={t("character.memory.placeholder")}
            value={memoryInput}
          />
          <AsyncButton disabled={!memoryName || !memoryInput.trim()} loading={addPending} onClick={onAddMemory}>
            {t("character.memory.add")}
          </AsyncButton>
        </div>
      ) : null}
    </section>
  );
}
