import { memo, useCallback, useState } from "react";
import type { ChangeEvent, UIEvent } from "react";
import { ArrowDown, ArrowUp, Music, Trash2, Upload } from "lucide-react";

import { fileUrl } from "../../entities/files/repository";
import { baseName } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, AudioPlayer, Button, EmptyState, FilePicker, PathDisplay, TextInput } from "../../shared/ui";
import type { BackgroundBgmItem, BgmSortDirection, BgmSortKey } from "./backgroundUtils";

const BGM_ROW_HEIGHT = 60;
const VIRTUAL_OVERSCAN_ROWS = 4;
const VIRTUAL_BGM_ROWS = 8;

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
  previewLabel: string;
  removeLabel: string;
  selected: boolean;
  selectLabel: string;
  tag: string;
  tagLabel: string;
}

const BackgroundBgmRow = memo(function BackgroundBgmRow({
  deleting,
  index,
  onDelete,
  onTagChange,
  onToggleSelection,
  path,
  previewLabel,
  removeLabel,
  selected,
  selectLabel,
  tag,
  tagLabel,
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
    <div aria-selected={selected} className="background-bgm-row" role="listitem">
      <div className="background-bgm-row__select">
        <input aria-label={`${selectLabel} ${index + 1}`} checked={selected} onChange={handleToggle} type="checkbox" />
      </div>
      <div className="background-bgm-row__index">{index + 1}</div>
      <div className="background-bgm-row__file">
        <span className="background-bgm-row__filename" title={filename}>
          <Music aria-hidden className="asset-row__icon" />
          <span>{filename}</span>
        </span>
        <PathDisplay className="background-bgm-row__path" path={path} />
      </div>
      <div className="background-bgm-row__tag">
        <TextInput aria-label={tagLabel} onChange={handleTagChange} placeholder={tagLabel} value={tag} />
      </div>
      <div className="background-bgm-row__preview" title={previewLabel}>
        {path ? <AudioPlayer compact label={`${previewLabel} ${filename}`} src={fileUrl(path)} /> : null}
      </div>
      <div className="background-bgm-row__actions">
        <AsyncButton
          aria-label={`${removeLabel} ${filename}`}
          className="background-bgm-row__remove"
          icon={<Trash2 aria-hidden className="button__icon" />}
          loading={deleting}
          onClick={handleDelete}
          tooltip={removeLabel}
          variant="ghost"
        />
      </div>
    </div>
  );
});

function BgmSpacer({ height }: { height: number }) {
  if (!height) {
    return null;
  }
  return <div aria-hidden className="background-bgm-list__spacer" style={{ height }} />;
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
    <div className="background-bgm-panel">
      <div className="background-bgm-list__header">
        <button
          aria-label={allSelected ? clearSelectionLabel : selectAllLabel}
          aria-pressed={allSelected}
          className="background-bgm-list__header-button background-bgm-list__header-button--center"
          onClick={onToggleAllSelection}
          title={allSelected ? clearSelectionLabel : selectAllLabel}
          type="button"
        >
          {selectLabel}
        </button>
        <button
          aria-label={indexAriaSort ? `${indexLabel} ${indexAriaSort}` : indexLabel}
          className="background-bgm-list__header-button background-bgm-list__header-button--center background-bgm-list__header-button--index"
          onClick={() => onSort("index")}
          type="button"
        >
          <span>{indexLabel}</span>
          {sortKey === "index" ? <SortIcon aria-hidden className="background-bgm-list__sort-indicator" /> : null}
        </button>
        <button
          aria-label={filenameAriaSort ? `${filenameLabel} ${filenameAriaSort}` : filenameLabel}
          className="background-bgm-list__header-button background-bgm-list__header-button--file"
          onClick={() => onSort("filename")}
          title={`${filenameLabel} / ${pathLabel}`}
          type="button"
        >
          <span>{filenameLabel}</span>
          {sortKey === "filename" ? <SortIcon aria-hidden className="background-bgm-list__sort-indicator" /> : null}
        </button>
        <span className="background-bgm-list__header-meta">{tagLabel}</span>
        <span className="background-bgm-list__header-meta">{previewLabel}</span>
        <span aria-hidden className="background-bgm-list__header-meta" />
      </div>
      <div
        className="background-bgm-list"
        onScroll={virtual.onScroll}
        role="list"
        style={{ maxHeight: virtual.maxHeight }}
      >
        <BgmSpacer height={virtual.paddingTop} />
        {visibleItems.map((item) => {
          return (
            <div
              className="background-bgm-list__slot"
              key={`${item.path}-${item.originalIndex}`}
              style={{ height: BGM_ROW_HEIGHT }}
            >
              <BackgroundBgmRow
                deleting={deleting}
                index={item.originalIndex}
                onDelete={onDelete}
                onTagChange={onTagChange}
                onToggleSelection={onToggleSelection}
                path={item.path}
                previewLabel={previewLabel}
                removeLabel={removeLabel}
                selectLabel={selectLabel}
                selected={selectedIndexes.has(item.originalIndex)}
                tag={rowTags[item.originalIndex] ?? ""}
                tagLabel={tagLabel}
              />
            </div>
          );
        })}
        <BgmSpacer height={virtual.paddingBottom} />
      </div>
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
  const canUploadBgm = Boolean(currentBackgroundName && pendingBgmPaths.length);
  const canDeleteSelectedBgm = Boolean(currentBackgroundName && selectedBgmIndexSet.size);
  const canClearBgm = Boolean(currentBackgroundName && bgmList.length);

  return (
    <section className="section background-music-section">
      <div className="section__header">
        <h2 className="section__title">{t("background.section.bgm")}</h2>
      </div>
      <div className="asset-editor">
        <div className="background-music-section__toolbar">
          <label className="field-row field-row--stack background-music-section__picker">
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
                  pendingBgmPaths.length ? t("background.asset.selectedFiles", { count: pendingBgmPaths.length }) : ""
                }
              />
            </span>
          </label>
          <div className="background-music-section__actions">
            <AsyncButton
              disabled={!canUploadBgm}
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
              disabled={!canDeleteSelectedBgm}
              icon={<Trash2 aria-hidden className="button__icon" />}
              loading={batchDeletePending}
              onClick={onBatchDelete}
              variant="ghost"
            >
              {t("background.asset.deleteSelectedBgm")}
            </AsyncButton>
            <Button
              disabled={!canClearBgm}
              icon={<Trash2 aria-hidden className="button__icon" />}
              onClick={onClearAll}
              variant="ghost"
            >
              {t("background.asset.clearBgm")}
            </Button>
          </div>
        </div>
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
