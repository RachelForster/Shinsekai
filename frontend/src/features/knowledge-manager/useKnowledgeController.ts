import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listKnowledgeEntries,
  listKnowledgeInstances,
  searchKnowledgeEntries,
  KnowledgeBrowseError,
} from "../../entities/knowledge/repository";
import { useI18n } from "../../shared/i18n";
import { useToast } from "../../shared/ui";
import { useKnowledgeModelReadiness } from "./useKnowledgeModelReadiness";

export function isKnowledgeLoading(error: unknown) {
  return error instanceof KnowledgeBrowseError && ["loading", "not_started"].includes(error.status);
}

const pollLoading = (query: { state: { error: Error | null } }) =>
  isKnowledgeLoading(query.state.error) ? 1000 : false;

export function useKnowledgeController() {
  const client = useQueryClient();
  const modelReadiness = useKnowledgeModelReadiness();
  const { ensureKnowledgeModelReady } = modelReadiness;
  const { t } = useI18n();
  const { showToast } = useToast();
  const lifecycle = useRef<AbortController | null>(null);
  const refreshCheck = useRef<Promise<void> | null>(null);
  const [refreshPending, setRefreshPending] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    lifecycle.current = controller;
    return () => controller.abort();
  }, []);
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [instancePickerOpen, setInstancePickerOpen] = useState(false);
  const [catalogTerm, setCatalogTerm] = useState("");
  const [catalogPage, setCatalogPage] = useState(1);
  const catalogSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelCatalogSearch = () => {
    if (catalogSearchTimer.current !== null) {
      clearTimeout(catalogSearchTimer.current);
      catalogSearchTimer.current = null;
    }
  };
  const closeInstances = () => {
    cancelCatalogSearch();
    setInstancePickerOpen(false);
  };
  useEffect(() => cancelCatalogSearch, []);
  const [selectedKnowledge, setSelectedKnowledge] = useState("");
  const [entryPage, setEntryPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchPage, setSearchPage] = useState(1);

  const resetPages = () => {
    setEntryPage(1);
    setSearchInput("");
    setSearchTerm("");
    setSearchPage(1);
  };

  const catalog = useQuery({
    queryKey: ["knowledge", "instances", catalogTerm, catalogPage],
    queryFn: () => listKnowledgeInstances({ query: catalogTerm, page: catalogPage }),
    enabled: instancePickerOpen,
    retry: false,
    refetchInterval: pollLoading,
  });
  const entries = useQuery({
    queryKey: ["knowledge", "entries", selectedKnowledge],
    queryFn: () => listKnowledgeEntries(selectedKnowledge),
    enabled: Boolean(selectedKnowledge) && !searchTerm,
    retry: false,
    refetchInterval: pollLoading,
  });
  const search = useQuery({
    queryKey: ["knowledge", "search", selectedKnowledge, searchTerm],
    queryFn: () => searchKnowledgeEntries(selectedKnowledge, searchTerm),
    enabled: Boolean(selectedKnowledge && searchTerm),
    retry: false,
    refetchInterval: pollLoading,
  });
  const activeEntriesQuery = searchTerm ? search : entries;
  const selectKnowledge = (id: string) => {
    cancelCatalogSearch();
    setSelectedKnowledge(id);
    setInstancePickerOpen(false);
    resetPages();
  };
  const searchInstances = () => {
    cancelCatalogSearch();
    setCatalogTerm(knowledgeQuery.trim());
    setCatalogPage(1);
    setInstancePickerOpen(true);
    void client.invalidateQueries({ queryKey: ["knowledge", "instances"] });
  };
  const refresh = (): Promise<void> => {
    if (refreshCheck.current) return refreshCheck.current;
    const signal = lifecycle.current?.signal;
    if (!signal || signal.aborted) return Promise.resolve();
    const run = async () => {
      setRefreshPending(true);
      try {
        if (!(await ensureKnowledgeModelReady({ retry: true })) || signal.aborted) return;
        setEntryPage(1);
        setSearchPage(1);
        await listKnowledgeInstances({ query: catalogTerm, page: catalogPage, refresh: true });
        if (!signal.aborted) await client.invalidateQueries({ queryKey: ["knowledge"] });
      } catch (error) {
        if (!signal.aborted)
          showToast({
            kind: "error",
            title: t("common.operationFailed"),
            message: error instanceof Error ? error.message : t("knowledge.loadFailed"),
          });
      } finally {
        if (!signal.aborted) setRefreshPending(false);
      }
    };
    refreshCheck.current = run().finally(() => {
      refreshCheck.current = null;
    });
    return refreshCheck.current;
  };
  const page = searchTerm ? searchPage : entryPage;
  const totalPages = Math.max(1, Math.ceil((activeEntriesQuery.data?.memories.length ?? 0) / 8));
  useEffect(() => {
    setEntryPage((p) => Math.min(p, Math.max(1, Math.ceil((entries.data?.memories.length ?? 0) / 8))));
  }, [entries.data]);
  useEffect(() => {
    setSearchPage((p) => Math.min(p, Math.max(1, Math.ceil((search.data?.memories.length ?? 0) / 8))));
  }, [search.data]);
  return {
    ...modelReadiness,
    instancePickerOpen,
    setInstancePickerOpen: (value: boolean) => {
      if (!value) closeInstances();
      else setInstancePickerOpen(true);
    },
    catalog,
    catalogPage,
    setCatalogPage,
    selectedKnowledge,
    selectKnowledge,
    searchInstances,
    refresh,
    refreshPending,
    knowledgeQuery,
    changeKnowledgeQuery: (value: string) => {
      cancelCatalogSearch();
      setKnowledgeQuery(value);
      setInstancePickerOpen(false);
      catalogSearchTimer.current = setTimeout(() => {
        catalogSearchTimer.current = null;
        setCatalogTerm(value.trim());
        setCatalogPage(1);
        setInstancePickerOpen(true);
      }, 300);
    },
    toggleInstances: () => {
      cancelCatalogSearch();
      if (instancePickerOpen) setInstancePickerOpen(false);
      else {
        setCatalogTerm("");
        setCatalogPage(1);
        setInstancePickerOpen(true);
      }
    },
    memories: searchTerm
      ? (search.data?.memories.slice((searchPage - 1) * 8, searchPage * 8) ?? [])
      : (entries.data?.memories.slice((entryPage - 1) * 8, entryPage * 8) ?? []),
    isFetching: activeEntriesQuery.isFetching,
    entriesView: {
      isFetching: activeEntriesQuery.isFetching,
      isLoading: activeEntriesQuery.isPending || isKnowledgeLoading(activeEntriesQuery.error),
      error: isKnowledgeLoading(activeEntriesQuery.error) ? null : activeEntriesQuery.error,
      page,
      totalPages,
      hasNext: page < totalPages,
      previous: () => {
        if (searchTerm) setSearchPage((p) => Math.max(1, p - 1));
        else setEntryPage((p) => Math.max(1, p - 1));
      },
      next: () => {
        if (searchTerm) setSearchPage((p) => Math.min(totalPages, p + 1));
        else setEntryPage((p) => Math.min(totalPages, p + 1));
      },
    },
    searchInput,
    setSearchInput,
    searchTerm,
    searchCount: search.data?.count ?? 0,
    searchEntries: () => {
      setSearchTerm(searchInput.trim());
      setSearchPage(1);
    },
    clearSearch: () => {
      setSearchInput("");
      setSearchTerm("");
      setSearchPage(1);
    },
  };
}
