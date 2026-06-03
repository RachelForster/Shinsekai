import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { Button, TextInput } from "../../shared/ui";

interface PagedSearchOptions<T> {
  items: T[];
  matcher: (item: T, query: string) => boolean;
  pageSize: number;
}

export function normalizePluginSearch(value: unknown) {
  return String(value ?? "")
    .trim()
    .toLowerCase();
}

export function searchablePluginText(values: unknown[]) {
  return values
    .map((value) => String(value ?? ""))
    .join(" ")
    .toLowerCase();
}

export function usePagedPluginList<T>({ items, matcher, pageSize }: PagedSearchOptions<T>) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const normalizedQuery = normalizePluginSearch(query);

  const filteredItems = useMemo(() => {
    if (!normalizedQuery) {
      return items;
    }
    return items.filter((item) => matcher(item, normalizedQuery));
  }, [items, matcher, normalizedQuery]);

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSize));

  useEffect(() => {
    setPage(1);
  }, [normalizedQuery, pageSize, items.length]);

  useEffect(() => {
    setPage((current) => Math.min(Math.max(current, 1), totalPages));
  }, [totalPages]);

  const startIndex = (page - 1) * pageSize;
  const pagedItems = filteredItems.slice(startIndex, startIndex + pageSize);

  return {
    filteredItems,
    page,
    pagedItems,
    query,
    setPage,
    setQuery,
    totalItems: items.length,
    totalPages,
  };
}

interface PluginListControlsProps {
  filteredCount: number;
  page: number;
  placeholder: string;
  query: string;
  setPage: Dispatch<SetStateAction<number>>;
  setQuery: Dispatch<SetStateAction<string>>;
  totalCount: number;
  totalPages: number;
}

export function PluginListControls({
  filteredCount,
  page,
  placeholder,
  query,
  setPage,
  setQuery,
  totalCount,
  totalPages,
}: PluginListControlsProps) {
  const { t } = useI18n();

  return (
    <div className="plugin-list-controls">
      <label className="plugin-list-controls__search">
        <Search aria-hidden className="plugin-list-controls__icon" />
        <TextInput
          aria-label={t("plugin.list.search")}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={placeholder}
          value={query}
        />
      </label>
      <span className="inline-status plugin-list-controls__count">
        {t("plugin.list.count", { count: filteredCount, total: totalCount })}
      </span>
      <div className="plugin-list-controls__pager" aria-label={t("plugin.list.pagination")}>
        <Button
          disabled={page <= 1}
          icon={<ChevronLeft aria-hidden className="button__icon" />}
          onClick={() => setPage((current) => Math.max(1, current - 1))}
          tooltip={t("plugin.list.previous")}
          variant="ghost"
        />
        <span className="inline-status">{t("plugin.list.page", { page, total: totalPages })}</span>
        <Button
          disabled={page >= totalPages}
          icon={<ChevronRight aria-hidden className="button__icon" />}
          onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
          tooltip={t("plugin.list.next")}
          variant="ghost"
        />
      </div>
    </div>
  );
}
