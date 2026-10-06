import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addKnowledgeEntry,
  deleteKnowledgeEntry,
  deleteKnowledge,
  batchKnowledgeBindings,
  listKnowledgeEntries,
  listKnowledgeInstances,
  searchKnowledgeEntries,
  KnowledgeBrowseError,
} from "../../entities/knowledge/repository";
import { useI18n } from "../../shared/i18n";
import { useToast } from "../../shared/ui";
import { useKnowledgeModelReadiness } from "./useKnowledgeModelReadiness";

export type KnowledgeDeleteTarget = { knowledgeId: string; memoryId?: string; content?: string };
type KnowledgeWrite = { knowledgeId: string } & (
  | { kind: "add-entry"; content: string }
  | { kind: "delete-entry"; memoryId: string }
  | { kind: "delete-knowledge" }
);

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
  const [memoryInput, setMemoryInput] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeDeleteTarget | null>(null);
  const writeLock = useRef(false);
  const activeScope = useRef({ knowledgeId: selectedKnowledge });
  activeScope.current = { knowledgeId: selectedKnowledge };
  const [entryPage, setEntryPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchPage, setSearchPage] = useState(1);

  const writeMutation = useMutation({
    mutationFn: async (input: KnowledgeWrite) => {
      if (!(await ensureKnowledgeModelReady())) return null;
      if (input.kind === "add-entry") return addKnowledgeEntry(input.knowledgeId, input.content);
      if (input.kind === "delete-entry") return deleteKnowledgeEntry(input.knowledgeId, input.memoryId);
      const result = await deleteKnowledge(input.knowledgeId);
      if (!result.ok) throw new Error(t("knowledge.loadFailed"));
      return result;
    },
    onSuccess(result, input) {
      if (!result) return;
      if ("memories" in result) client.setQueryData(["knowledge", "entries", input.knowledgeId], result);
      else {
        for (const kind of ["entries", "search", "binding-names"]) {
          client.removeQueries({ queryKey: ["knowledge", kind, input.knowledgeId] });
        }
      }
      if (activeScope.current.knowledgeId === input.knowledgeId) {
        if (input.kind === "add-entry") {
          setMemoryInput("");
          resetPages();
        } else {
          setDeleteTarget(null);
          if (input.kind === "delete-knowledge") {
            setSelectedKnowledge("");
            setKnowledgeQuery("");
            resetPages();
          }
        }
      }
      showToast({
        kind: "success",
        title: t(input.kind === "add-entry" ? "knowledge.saved" : "knowledge.deleted"),
      });
    },
    onError(error) {
      showToast({ kind: "error", title: t("common.operationFailed"), message: error.message });
    },
    async onSettled() {
      // A failed knowledge deletion may already have removed entries or bindings.
      await client.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });
  const runWrite = async (input: KnowledgeWrite) => {
    if (writeLock.current) return;
    writeLock.current = true;
    try {
      await writeMutation.mutateAsync(input);
    } catch {
      /* onError reports the failure; retain the input or confirmation. */
    } finally {
      writeLock.current = false;
    }
  };

  const batchBindingLock = useRef(false);
  const batchBindingMutation = useMutation({
    mutationFn: ({ knowledge, add, remove }: { knowledge: string; add: string[]; remove: string[] }) =>
      batchKnowledgeBindings(knowledge, add, remove),
    onSuccess: async (result) => {
      client.setQueryData(["knowledge", "binding-names", result.knowledge_id], result);
      await client.invalidateQueries({ queryKey: ["knowledge"] });
      showToast({ kind: "success", title: t("knowledge.saved") });
    },
  });

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
    setMemoryInput("");
    setDeleteTarget(null);
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
    memoryInput,
    setMemoryInput,
    deleteTarget,
    writePending: writeMutation.isPending,
    addPending: writeMutation.isPending && writeMutation.variables?.kind === "add-entry",
    deletePending: writeMutation.isPending && writeMutation.variables?.kind !== "add-entry",
    deletingMemoryId:
      writeMutation.isPending && writeMutation.variables?.kind === "delete-entry"
        ? writeMutation.variables.memoryId
        : null,
    addEntry: () => {
      if (selectedKnowledge && memoryInput.trim())
        void runWrite({ kind: "add-entry", knowledgeId: selectedKnowledge, content: memoryInput.trim() });
    },
    requestDeleteEntry: (entry: { id: string; memory: string }) => {
      if (selectedKnowledge && entry.id && !writeLock.current)
        setDeleteTarget({ knowledgeId: selectedKnowledge, memoryId: entry.id, content: entry.memory });
    },
    requestDeleteKnowledge: () => {
      if (selectedKnowledge && !writeLock.current) setDeleteTarget({ knowledgeId: selectedKnowledge });
    },
    cancelDelete: () => {
      if (!writeLock.current) setDeleteTarget(null);
    },
    confirmDelete: () => {
      if (!deleteTarget) return;
      const scope = { knowledgeId: deleteTarget.knowledgeId };
      void runWrite(
        deleteTarget.memoryId
          ? { ...scope, kind: "delete-entry", memoryId: deleteTarget.memoryId }
          : { ...scope, kind: "delete-knowledge" },
      );
    },
    ...modelReadiness,
    saveBindings: async (add: string[], remove: string[]) => {
      if (!selectedKnowledge || batchBindingLock.current || writeLock.current) return false;
      batchBindingLock.current = true;
      try {
        await batchBindingMutation.mutateAsync({ knowledge: selectedKnowledge, add, remove });
        return true;
      } catch {
        return false;
      } finally {
        batchBindingLock.current = false;
      }
    },
    batchBindingPending: batchBindingMutation.isPending,
    bindingPending: batchBindingMutation.isPending,
    bindingError: batchBindingMutation.variables?.knowledge === selectedKnowledge ? batchBindingMutation.error : null,
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
