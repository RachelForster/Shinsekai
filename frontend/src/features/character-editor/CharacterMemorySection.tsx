import { useEffect, useRef, useState } from "react";
import {
  Brain,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Pin,
  PinOff,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { CharacterMemory, CharacterMemoryClarity, CharacterMemoryList } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, QueryErrorState, Switch, TextInput } from "../../shared/ui";

interface CharacterMemorySectionProps {
  addAsCanon?: boolean;
  addPending: boolean;
  awakenPending?: boolean;
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
  memoryImportPending: boolean;
  memoryName: string;
  memoryPage: number;
  memoryTotalPages: number;
  activeSearchQuery: string;
  onAddAsCanonChange?: (value: boolean) => void;
  onAddMemory: () => void;
  onAwakenMemory?: (memory: CharacterMemory) => void;
  onClearSearch: () => void;
  onDeleteMemory: (memory: { id: string; memory: string }) => void;
  onInstallDep: () => void;
  onImportMemories: () => void;
  onMemoryInputChange: (value: string) => void;
  onMemoryPageChange: (updater: (page: number) => number) => void;
  onPinMemory?: (memory: CharacterMemory, pinned: boolean) => void;
  onRefresh: () => void;
  onSearch: () => void;
  onSearchInputChange: (value: string) => void;
  pinPending?: boolean;
  searchInput: string;
  searchPending: boolean;
  /** Multi-select support. When `onToggleSelected` is omitted the selection UI is hidden. */
  selectedIds?: ReadonlySet<string>;
  totalCount?: number;
  /** Memories currently loaded client-side (one backend window, or all search results). */
  loadedCount?: number;
  deleteManyPending?: boolean;
  exportPending?: boolean;
  onToggleSelected?: (memoryId: string, selected: boolean) => void;
  onSetManySelected?: (memoryIds: string[], selected: boolean) => void;
  onSelectAll?: () => void;
  onClearSelection?: () => void;
  onDeleteSelected?: (memoryIds: string[]) => void;
  onExportMemories?: () => void;
}

const EMPTY_SELECTION: ReadonlySet<string> = new Set();

function SelectAllCheckbox({
  checked,
  disabled,
  indeterminate,
  label,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  indeterminate: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.indeterminate = indeterminate;
    }
  }, [indeterminate]);
  return (
    <label className="memory-select memory-bulk-bar__page-toggle">
      <input
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.checked)}
        ref={ref}
        type="checkbox"
      />
      <span>{label}</span>
    </label>
  );
}

function isCanonMemory(memory: CharacterMemory): boolean {
  return Boolean(memory.pinned || memory.clarity === "canon" || memory.kind === "canon");
}

function resolveMemoryClarity(memory: CharacterMemory): CharacterMemoryClarity | undefined {
  if (isCanonMemory(memory)) {
    return "canon";
  }
  return memory.clarity;
}

export function CharacterMemorySection({
  addAsCanon = false,
  addPending,
  awakenPending = false,
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
  memoryImportPending,
  memoryName,
  memoryPage,
  memoryTotalPages,
  activeSearchQuery,
  onAddAsCanonChange,
  onAddMemory,
  onAwakenMemory,
  onClearSearch,
  onDeleteMemory,
  onInstallDep,
  onImportMemories,
  onMemoryInputChange,
  onMemoryPageChange,
  onPinMemory,
  onRefresh,
  onSearch,
  onSearchInputChange,
  pinPending = false,
  searchInput,
  searchPending,
  selectedIds = EMPTY_SELECTION,
  totalCount,
  loadedCount,
  deleteManyPending = false,
  exportPending = false,
  onToggleSelected,
  onSetManySelected,
  onSelectAll,
  onClearSelection,
  onDeleteSelected,
  onExportMemories,
}: CharacterMemorySectionProps) {
  const { t } = useI18n();
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});
  const memories = data?.memories ?? [];
  const hasMemoryRows = memories.length > 0;
  const selectable = Boolean(onToggleSelected);
  const pageIds = memories.map((memory) => memory.id).filter(Boolean);
  const pageSelectedCount = pageIds.filter((memoryId) => selectedIds.has(memoryId)).length;
  const allPageSelected = pageIds.length > 0 && pageSelectedCount === pageIds.length;
  const selectedCount = selectedIds.size;
  const visibleTotal = totalCount ?? data?.total ?? memories.length;
  const loadedTotal = loadedCount ?? memories.length;
  const bulkBusy = deleteManyPending || deletePending;
  const hasRichMetadata = memories.some(
    (memory) =>
      memory.clarity !== undefined ||
      memory.pinned !== undefined ||
      memory.retention !== undefined ||
      memory.gist !== undefined ||
      memory.detail !== undefined,
  );
  const canonMemories = hasRichMetadata ? memories.filter(isCanonMemory) : [];
  const dynamicMemories = hasRichMetadata ? memories.filter((memory) => !isCanonMemory(memory)) : memories;

  const toggleExpand = (memoryId: string) => {
    setExpandedIds((current) => ({ ...current, [memoryId]: !current[memoryId] }));
  };

  const renderMemoryRow = (memory: CharacterMemory) => {
    const canon = isCanonMemory(memory);
    const clarity = resolveMemoryClarity(memory);
    const headline = memory.gist?.trim() || memory.memory;
    const rawDetail = memory.detail?.trim() || (memory.gist?.trim() && memory.memory !== headline ? memory.memory : "");
    const hasExpandableDetail = Boolean(rawDetail && rawDetail !== headline);
    const expanded = Boolean(memory.id && expandedIds[memory.id]);
    const retentionPct =
      typeof memory.retention === "number" && Number.isFinite(memory.retention)
        ? Math.round(Math.max(0, Math.min(1, memory.retention)) * 100)
        : null;
    const canAwaken = Boolean(
      onAwakenMemory &&
      memory.id &&
      !canon &&
      (clarity === "faded" || clarity === "dormant" || (retentionPct !== null && retentionPct < 85)),
    );

    const selected = Boolean(memory.id && selectedIds.has(memory.id));

    return (
      <div
        className={`memory-row${selectable ? " memory-row--selectable" : ""}${selected ? " memory-row--selected" : ""}`}
        data-clarity={clarity}
        key={memory.id || memory.memory}
      >
        {selectable ? (
          <label className="memory-select memory-row__select">
            <input
              aria-label={`${t("character.memory.select")}: ${headline}`}
              checked={selected}
              disabled={!memory.id || bulkBusy}
              onChange={(event) => onToggleSelected?.(memory.id, event.currentTarget.checked)}
              type="checkbox"
            />
          </label>
        ) : null}
        {canon ? <Pin aria-hidden className="asset-row__icon" /> : <Brain aria-hidden className="asset-row__icon" />}
        <div className="memory-row__content">
          <strong>{headline}</strong>
          <div className="memory-row__meta">
            {clarity ? (
              <span className={`memory-clarity-badge memory-clarity-badge--${clarity}`}>
                {t(`character.memory.clarity.${clarity}`)}
              </span>
            ) : null}
            {!canon && retentionPct !== null ? (
              <span className="memory-retention">
                <span aria-hidden className="memory-retention__track">
                  <span className="memory-retention__fill" style={{ width: `${retentionPct}%` }} />
                </span>
                <span className="memory-retention__label">
                  {t("character.memory.retentionValue", { percent: retentionPct })}
                </span>
              </span>
            ) : null}
            <span>{memory.id}</span>
          </div>
          {hasExpandableDetail && expanded ? <p className="memory-row__detail">{rawDetail}</p> : null}
        </div>
        <div className="memory-row__actions">
          {hasExpandableDetail && memory.id ? (
            <Button onClick={() => toggleExpand(memory.id)} variant="ghost">
              {t(expanded ? "character.memory.collapseDetail" : "character.memory.expandDetail")}
            </Button>
          ) : null}
          {canAwaken ? (
            <AsyncButton
              disabled={!memory.id}
              icon={<Sparkles aria-hidden className="button__icon" />}
              loading={awakenPending}
              onClick={() => onAwakenMemory?.(memory)}
              variant="ghost"
            >
              {t("character.memory.awaken")}
            </AsyncButton>
          ) : null}
          {onPinMemory ? (
            <AsyncButton
              disabled={!memory.id}
              icon={
                canon ? <PinOff aria-hidden className="button__icon" /> : <Pin aria-hidden className="button__icon" />
              }
              loading={pinPending}
              onClick={() => {
                if (!memory.id) {
                  return;
                }
                onPinMemory(memory, !canon);
              }}
              variant="ghost"
            >
              {t(canon ? "character.memory.unpin" : "character.memory.pin")}
            </AsyncButton>
          ) : null}
          <AsyncButton
            disabled={!memory.id}
            loading={deletePending}
            onClick={() => {
              if (!memory.id) {
                return;
              }
              onDeleteMemory({ id: memory.id, memory: headline });
            }}
            variant="ghost"
          >
            {t("character.memory.delete")}
          </AsyncButton>
        </div>
      </div>
    );
  };

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.memory.section")}</h2>
        <div className="page__actions">
          <span className="entity-list__meta">
            {data ? t("character.memory.count", { count: totalCount ?? data.total ?? data.count }) : ""}
          </span>
          <AsyncButton
            disabled={!memoryName || Boolean(depError) || depInstalling || isChecking}
            icon={<Upload aria-hidden className="button__icon" />}
            loading={memoryImportPending}
            onClick={onImportMemories}
            variant="ghost"
          >
            {t("character.memory.import")}
          </AsyncButton>
          {onExportMemories ? (
            <AsyncButton
              disabled={!memoryName || Boolean(depError) || isChecking || visibleTotal === 0}
              icon={<FileText aria-hidden className="button__icon" />}
              loading={exportPending}
              onClick={onExportMemories}
              variant="ghost"
            >
              {selectedCount > 0
                ? t("character.memory.exportSelectedTxt", { count: selectedCount })
                : t("character.memory.exportTxt")}
            </AsyncButton>
          ) : null}
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
      {memoryName && isFetched && !isLoading && !isError && !depError && !hasMemoryRows ? (
        <EmptyState title={activeSearchQuery ? t("character.memory.searchEmpty") : t("character.memory.empty")} />
      ) : null}
      {hasMemoryRows && selectable ? (
        <div className="memory-bulk-bar" role="toolbar" aria-label={t("character.memory.select")}>
          <div className="memory-bulk-bar__group">
            <SelectAllCheckbox
              checked={allPageSelected}
              disabled={pageIds.length === 0 || bulkBusy}
              indeterminate={pageSelectedCount > 0 && !allPageSelected}
              label={t("character.memory.selectPage")}
              onChange={(checked) => onSetManySelected?.(pageIds, checked)}
            />
            {onSelectAll && loadedTotal > pageIds.length ? (
              <Button disabled={bulkBusy} onClick={onSelectAll} variant="ghost">
                {t("character.memory.selectAll", { count: loadedTotal })}
              </Button>
            ) : null}
            {selectedCount > 0 ? (
              <>
                <span className="inline-status memory-bulk-bar__count">
                  {t("character.memory.selectedCount", { count: selectedCount })}
                </span>
                {onClearSelection ? (
                  <Button disabled={bulkBusy} onClick={onClearSelection} variant="ghost">
                    {t("character.memory.clearSelection")}
                  </Button>
                ) : null}
              </>
            ) : null}
          </div>
          {onDeleteSelected ? (
            <AsyncButton
              disabled={selectedCount === 0 || Boolean(depError) || isChecking}
              icon={<Trash2 aria-hidden className="button__icon" />}
              loading={deleteManyPending}
              onClick={() => onDeleteSelected(Array.from(selectedIds))}
              variant="danger"
            >
              {t("character.memory.deleteSelected", { count: selectedCount })}
            </AsyncButton>
          ) : null}
        </div>
      ) : null}
      {hasMemoryRows ? (
        <div className="memory-table">
          {hasRichMetadata ? (
            <>
              {canonMemories.length > 0 ? (
                <div className="memory-group">
                  <h3 className="memory-group__title">{t("character.memory.canonSection")}</h3>
                  <div className="memory-group__rows">{canonMemories.map(renderMemoryRow)}</div>
                </div>
              ) : null}
              {dynamicMemories.length > 0 ? (
                <div className="memory-group">
                  <h3 className="memory-group__title">{t("character.memory.dynamicSection")}</h3>
                  <div className="memory-group__rows">{dynamicMemories.map(renderMemoryRow)}</div>
                </div>
              ) : null}
            </>
          ) : (
            memories.map(renderMemoryRow)
          )}
        </div>
      ) : null}
      {hasMemoryRows || (Boolean(memoryName) && !depError && memoryTotalPages > 1) ? (
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
        <div className="memory-add-stack">
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
          {onAddAsCanonChange ? (
            <Switch
              checked={addAsCanon}
              disabled={!memoryName}
              id="character-memory-add-canon"
              onChange={(event) => onAddAsCanonChange(event.currentTarget.checked)}
            >
              {t("character.memory.addAsCanon")}
            </Switch>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
