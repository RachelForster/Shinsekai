import { memo, useCallback, useState } from "react";
import type { ChangeEvent, UIEvent } from "react";
import { ArrowDown, ArrowUp, Music, Trash2, Upload } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { baseName } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, EmptyState, FilePicker, PathDisplay, TextInput } from "../../shared/ui";
import type { BackgroundBgmItem, BgmSortDirection, BgmSortKey } from "./backgroundUtils";

const BGM_ROW_HEIGHT = 58;
const VIRTUAL_OVERSCAN_ROWS = 4;
const VIRTUAL_BGM_ROWS = 10;

/* ── Virtual scroll hook ── */

function useVirtualRange(count: number, rowHeight: number, visibleRows: number) {
  const [scrollTop, setScrollTop] = useState(0);
  const viewportHeight = Math.max(rowHeight, Math.min(count || 1, visibleRows) * rowHeight);
  const maxScrollTop = Math.max(0, count * rowHeight - viewportHeight);
  const clampedScrollTop = Math.min(scrollTop, maxScrollTop);
  const startIndex = Math.max(0, Math.floor(clampedScrollTop / rowHeight) - VIRTUAL_OVERSCAN_ROWS);
  const endIndex = Math.min(count, startIndex + visibleRows + VIRTUAL_OVERSCAN_ROWS * 2);
  const onScroll = useCallback((event: UIEvent<HTMLElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  }, []);

  return {
    endIndex,
    maxHeight: count > visibleRows ? viewportHeight : undefined,
    onScroll,
    paddingBottom: Math.max(0, (count - endIndex) * rowHeight),
    paddingTop: startIndex * rowHeight,
    startIndex,
  };
}

/* ── Internal BGM row components ── */

interface BackgroundBgmRowProps {
  deleting: boolean;
  index: number;
  onDelete: (index: number) => void;
  onTagChange: (index: number, value: string) => void;
  onToggleSelection: (index: number, checked: boolean) => void;
  path: string;
  removeLabel: string;
  selected: boolean;
  tag: string;
}

const BackgroundBgmRow = memo(function BackgroundBgmRow({
  deleting,
  index,
  onDelete,
  onTagChange,
  onToggleSelection,
  path,
  removeLabel,
  selected,
  tag,
}: BackgroundBgmRowProps) {
  const handleDelete = useCallback(() => onDelete(index), [index, onDelete]);
  const handleTagChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => onTagChange(index, event.target.value),
    [index, onTagChange],
  );
  const handleToggle = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => onToggleSelection(index, event.target.checked),
    [index, onToggleSelection],
  );
  const filename = baseName(path);

  return (
    <tr aria-selected={selected}>
      <td>
        <input checked={selected} onChange={handleToggle} type="checkbox" />
      </td>
      <td>{index + 1}</td>
      <td className="background-bgm-table__filename" title={filename}>
        <span className="background-bgm-table__filename-inner">
          <Music aria-hidden className="asset-row__icon" />
          <span>{filename}</span>
        </span>
      </td>
      <td>
        <PathDisplay className="background-bgm-table__path" path={path} />
      </td>
      <td className="background-bgm-table__tag">
        <TextInput onChange={handleTagChange} value={tag} />
      </td>
      <td className="background-bgm-table__preview">
        {path ? <audio className="audio-inline" controls preload="none" src={fileUrl(path)} /> : null}
      </td>
      <td>
        <AsyncButton
          icon={<Trash2 aria-hidden className="button__icon" />}
          loading={deleting}
          onClick={handleDelete}
          variant="ghost"
        >
          {removeLabel}
        </AsyncButton>
      </td>
    </tr>
  );
});

function BgmSpacerRow({ height }: { height: number }) {
  if (!height) {
    return null;
  }
  return (
    <tr aria-hidden className="background-virtual-table__spacer">
      <td colSpan={7} style={{ height }} />
    </tr>
  );
}

interface BackgroundBgmRowsProps {
  allSelected: boolean;
  clearSelectionLabel: string;
  deleting: boolean;
  filenameLabel: string;
  items: BackgroundBgmItem[];
  indexLabel: string;
  onDelete: (index: number) => void;
  onSort: (key: BgmSortKey) => void;
  onToggleAllSelection: () => void;
  onTagChange: (index: number, value: string) => void;
  onToggleSelection: (index: number, checked: boolean) => void;
  pathLabel: string;
  previewLabel: string;
  removeLabel: string;
  rowTags: string[];
  selectLabel: string;
  selectAllLabel: string;
  selectedIndexes: Set<number>;
  sortDirection: BgmSortDirection;
  sortKey: BgmSortKey;
  tagLabel: string;
}

const BackgroundBgmRows = memo(function BackgroundBgmRows({
  allSelected,
  clearSelectionLabel,
  deleting,
  filenameLabel,
  items,
  indexLabel,
  onDelete,
  onSort,
  onToggleAllSelection,
  onTagChange,
  onToggleSelection,
  pathLabel,
  previewLabel,
  removeLabel,
  rowTags,
  selectLabel,
  selectAllLabel,
  selectedIndexes,
  sortDirection,
  sortKey,
  tagLabel,
}: BackgroundBgmRowsProps) {
  const virtual = useVirtualRange(items.length, BGM_ROW_HEIGHT, VIRTUAL_BGM_ROWS);
  const visibleItems = items.slice(virtual.startIndex, virtual.endIndex);
  const indexAriaSort = sortKey === "index" ? (sortDirection === "asc" ? "ascending" : "descending") : undefined;
  const filenameAriaSort = sortKey === "filename" ? (sortDirection === "asc" ? "ascending" : "descending") : undefined;
  const SortIcon = sortDirection === "asc" ? ArrowUp : ArrowDown;

  return (
    <div
      className="data-table-wrap background-virtual-table"
      onScroll={virtual.onScroll}
      style={{ maxHeight: virtual.maxHeight }}
    >
      <table className="data-table background-bgm-table">
        <colgroup>
          <col className="background-bgm-table__select-col" />
          <col className="background-bgm-table__index-col" />
          <col className="background-bgm-table__filename-col" />
          <col className="background-bgm-table__path-col" />
          <col className="background-bgm-table__tag-col" />
          <col className="background-bgm-table__preview-col" />
          <col className="background-bgm-table__remove-col" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <button
                aria-label={allSelected ? clearSelectionLabel : selectAllLabel}
                aria-pressed={allSelected}
                className="background-bgm-table__header-button"
                onClick={onToggleAllSelection}
                title={allSelected ? clearSelectionLabel : selectAllLabel}
                type="button"
              >
                {selectLabel}
              </button>
            </th>
            <th aria-sort={indexAriaSort}>
              <button className="background-bgm-table__header-button" onClick={() => onSort("index")} type="button">
                <span>{indexLabel}</span>
                {sortKey === "index" ? <SortIcon aria-hidden className="background-bgm-table__sort-indicator" /> : null}
              </button>
            </th>
            <th aria-sort={filenameAriaSort}>
              <button className="background-bgm-table__header-button" onClick={() => onSort("filename")} type="button">
                <span>{filenameLabel}</span>
                {sortKey === "filename" ? (
                  <SortIcon aria-hidden className="background-bgm-table__sort-indicator" />
                ) : null}
              </button>
            </th>
            <th>{pathLabel}</th>
            <th>{tagLabel}</th>
            <th>{previewLabel}</th>
            <th>{removeLabel}</th>
          </tr>
        </thead>
        <tbody>
          <BgmSpacerRow height={virtual.paddingTop} />
          {visibleItems.map((item) => {
            return (
              <BackgroundBgmRow
                deleting={deleting}
                index={item.originalIndex}
                key={`${item.path}-${item.originalIndex}`}
                onDelete={onDelete}
                onTagChange={onTagChange}
                onToggleSelection={onToggleSelection}
                path={item.path}
                removeLabel={removeLabel}
                selected={selectedIndexes.has(item.originalIndex)}
                tag={rowTags[item.originalIndex] ?? ""}
              />
            );
          })}
          <BgmSpacerRow height={virtual.paddingBottom} />
        </tbody>
      </table>
    </div>
  );
});

/* ── Public section component ── */

interface BackgroundMusicSectionProps {
  batchDeletePending: boolean;
  bgmList: string[];
  bgmRowTags: string[];
  currentBackgroundName: string;
  deletePending: boolean;
  onBatchDelete: () => void;
  onClearAll: () => void;
  onDelete: (index: number) => void;
  onPendingBgmPathsChange: (paths: string[]) => void;
  onSortToggle: (key: BgmSortKey) => void;
  onTagChange: (index: number, value: string) => void;
  onToggleAllSelection: () => void;
  onToggleSelection: (index: number, checked: boolean) => void;
  onUpload: () => void;
  pendingBgmPaths: string[];
  selectedBgmIndexSet: Set<number>;
  sortDirection: BgmSortDirection;
  sortKey: BgmSortKey;
  sortedBgmItems: BackgroundBgmItem[];
  uploadPending: boolean;
}

export function BackgroundMusicSection({
  batchDeletePending,
  bgmList,
  bgmRowTags,
  currentBackgroundName,
  deletePending,
  onBatchDelete,
  onClearAll,
  onDelete,
  onPendingBgmPathsChange,
  onSortToggle,
  onTagChange,
  onToggleAllSelection,
  onToggleSelection,
  onUpload,
  pendingBgmPaths,
  selectedBgmIndexSet,
  sortDirection,
  sortKey,
  sortedBgmItems,
  uploadPending,
}: BackgroundMusicSectionProps) {
  const { t } = useI18n();
  const allBgmSelected = bgmList.length > 0 && selectedBgmIndexSet.size === bgmList.length;

  return (
    <section className="section">
      <div className="section__header">
        <h2 className="section__title">{t("background.section.bgm")}</h2>
        <div className="page__actions">
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={uploadPending}
            onClick={() => {
              if (!currentBackgroundName || !pendingBgmPaths.length) {
                return;
              }
              onUpload();
            }}
            variant="ghost"
          >
            {t("background.asset.uploadBgm")}
          </AsyncButton>
          <AsyncButton
            icon={<Trash2 aria-hidden className="button__icon" />}
            loading={batchDeletePending}
            onClick={onBatchDelete}
            variant="ghost"
          >
            {t("background.asset.deleteSelectedBgm")}
          </AsyncButton>
          <Button
            icon={<Trash2 aria-hidden className="button__icon" />}
            onClick={onClearAll}
            variant="ghost"
          >
            {t("background.asset.clearBgm")}
          </Button>
        </div>
      </div>
      <div className="asset-editor">
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("background.asset.selectBgm")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
              multiple
              onPathsChange={(paths) => {
                if (paths.length) {
                  onPendingBgmPathsChange(paths);
                }
              }}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("background.asset.selectBgm")}
              value={
                pendingBgmPaths.length
                  ? t("background.asset.selectedFiles", { count: pendingBgmPaths.length })
                  : ""
              }
            />
          </span>
        </label>
        {!bgmList.length ? <EmptyState title={t("background.asset.emptyBgm")} /> : null}
        {bgmList.length ? (
          <BackgroundBgmRows
            allSelected={allBgmSelected}
            clearSelectionLabel={t("background.asset.clearBgmSelection")}
            deleting={deletePending}
            filenameLabel={t("background.asset.filename")}
            items={sortedBgmItems}
            indexLabel={t("background.asset.index")}
            onDelete={onDelete}
            onSort={onSortToggle}
            onTagChange={onTagChange}
            onToggleAllSelection={onToggleAllSelection}
            onToggleSelection={onToggleSelection}
            pathLabel={t("background.asset.path")}
            previewLabel={t("background.asset.preview")}
            removeLabel={t("common.remove")}
            rowTags={bgmRowTags}
            selectLabel={t("background.asset.select")}
            selectAllLabel={t("background.asset.selectAllBgm")}
            selectedIndexes={selectedBgmIndexSet}
            sortDirection={sortDirection}
            sortKey={sortKey}
            tagLabel={t("background.asset.tag")}
          />
        ) : null}
      </div>
    </section>
  );
}
