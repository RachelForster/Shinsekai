import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  awakenCharacterMemory,
  deleteCharacterMemories,
  deleteCharacterMemory,
  exportCharacterMemories,
  getMem0Status,
  listCharacterMemories,
  pinCharacterMemory,
  rememberCharacterMemory,
  searchCharacterMemories,
} from "../../entities/character/repository";
import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import { useI18n } from "../../shared/i18n";
import type { CharacterMemoryList, TaskSnapshot } from "../../shared/platform/types";
import { useToast } from "../../shared/ui";
import { saveMemoriesTextFile } from "./memoryExport";

/** Rows shown per page. */
export const MEMORY_PAGE_SIZE = 10;
/** Rows fetched from the backend per request; one window covers MEMORY_WINDOW_SIZE / MEMORY_PAGE_SIZE pages. */
export const MEMORY_WINDOW_SIZE = 200;
const PAGES_PER_WINDOW = MEMORY_WINDOW_SIZE / MEMORY_PAGE_SIZE;
const MEMORY_SEARCH_LIMIT = 200;

const memoryQueryRoot = (name: string) => ["character-memories", name] as const;
const memoryQueryKey = (name: string, offset: number) => ["character-memories", name, offset] as const;

interface UseCharacterMemoryControllerOptions {
  displayName?: string;
  memoryName: string;
}

export function useCharacterMemoryController({ displayName, memoryName }: UseCharacterMemoryControllerOptions) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const [memoryInput, setMemoryInput] = useState("");
  const [addAsCanon, setAddAsCanon] = useState(false);
  const [memoryDepOpen, setMemoryDepOpen] = useState(false);
  const [memoryDepInstalling, setMemoryDepInstalling] = useState(false);
  const [memoryDepTask, setMemoryDepTask] = useState<TaskSnapshot | null>(null);
  const [mem0LoadingOpen, setMem0LoadingOpen] = useState(false);
  const [mem0LoadingMessage, setMem0LoadingMessage] = useState("");
  const [mem0Task, setMem0Task] = useState<TaskSnapshot | null>(null);
  const [mem0Checking, setMem0Checking] = useState(false);
  const [listPage, setListPage] = useState(1);
  const [searchPage, setSearchPage] = useState(1);
  const [searchData, setSearchData] = useState<Awaited<ReturnType<typeof searchCharacterMemories>> | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearchQuery, setActiveSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [exportPending, setExportPending] = useState(false);
  // Automatic window fetching only starts once mem0 readiness was confirmed for this character.
  const [listEnabledFor, setListEnabledFor] = useState<string | null>(null);

  const listOffset = Math.floor((Math.max(1, listPage) - 1) / PAGES_PER_WINDOW) * MEMORY_WINDOW_SIZE;

  const reportMem0StatusError = (error: unknown) => {
    console.error("Failed to get mem0 status", error);
    setMem0Task(null);
    setMem0LoadingOpen(false);
    setMem0LoadingMessage(t("character.memory.error"));
    showToast({
      kind: "error",
      message: error instanceof Error ? error.message : t("character.memory.error"),
      title: t("common.operationFailed"),
    });
  };

  const query = useQuery({
    enabled: Boolean(memoryName) && listEnabledFor === memoryName,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === memoryName ? keepPreviousData(previous) : undefined,
    queryFn: () => listCharacterMemories(memoryName, { limit: MEMORY_WINDOW_SIZE, offset: listOffset }),
    queryKey: memoryQueryKey(memoryName, listOffset),
  });

  const searchMutation = useMutation({
    mutationFn: searchCharacterMemories,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.search"),
      });
    },
    onSuccess(result, variables) {
      const nextQuery = variables.query.trim();
      if (nextQuery !== activeSearchQuery) {
        setSelectedIds(new Set());
      }
      setActiveSearchQuery(nextQuery);
      setSearchData(result);
      setSearchPage(1);
    },
  });

  const depError: { kind: string; moduleName: string; packageName: string } | null = useMemo(() => {
    const data = query.data as Record<string, unknown> | undefined;
    if (data && typeof data.kind === "string" && data.kind === "missing_dependency") {
      return {
        kind: data.kind,
        moduleName: String(data.moduleName || ""),
        packageName: String(data.packageName || ""),
      };
    }
    return null;
  }, [query.data]);

  const searching = Boolean(activeSearchQuery);
  const memoryPage = searching ? searchPage : listPage;
  const listData = depError ? undefined : query.data;
  // While a new window loads, react-query keeps the previous window as placeholder; never slice it.
  const listWindowPending = Boolean(listData && query.isPlaceholderData);
  const listTotal = listData ? (listData.total ?? (listData.offset ?? listOffset) + listData.memories.length) : 0;
  const totalCount = depError ? 0 : searching ? (searchData?.memories.length ?? 0) : listTotal;
  const loadedMemories: CharacterMemoryList["memories"] = depError
    ? []
    : searching
      ? (searchData?.memories ?? [])
      : listWindowPending
        ? []
        : (listData?.memories ?? []);
  const memoryTotalPages = Math.max(1, Math.ceil(totalCount / MEMORY_PAGE_SIZE));

  const pagedData = useMemo((): CharacterMemoryList | undefined => {
    if (depError) {
      return undefined;
    }
    if (searching) {
      if (!searchData) return undefined;
      const start = (searchPage - 1) * MEMORY_PAGE_SIZE;
      return {
        ...searchData,
        memories: searchData.memories.slice(start, start + MEMORY_PAGE_SIZE),
        total: searchData.memories.length,
      };
    }
    if (!listData) {
      return undefined;
    }
    if (listWindowPending) {
      return { ...listData, count: 0, memories: [], total: listTotal };
    }
    const windowOffset = listData.offset ?? listOffset;
    const start = Math.max(0, (listPage - 1) * MEMORY_PAGE_SIZE - windowOffset);
    return {
      ...listData,
      memories: listData.memories.slice(start, start + MEMORY_PAGE_SIZE),
      total: listTotal,
    };
  }, [depError, listData, listOffset, listPage, listTotal, listWindowPending, searchData, searchPage, searching]);

  const setMemoryPage = (updater: number | ((page: number) => number)) => {
    const apply = (current: number) => (typeof updater === "function" ? updater(current) : updater);
    if (searching) {
      setSearchPage(apply);
    } else {
      setListPage(apply);
    }
  };

  useEffect(() => {
    setAddAsCanon(false);
    setSearchInput("");
    setActiveSearchQuery("");
    setSearchData(null);
    setListPage(1);
    setSearchPage(1);
    setSelectedIds(new Set());
  }, [memoryName]);

  // Clamp the page once the real total is known (e.g. after deletions shrink the list).
  useEffect(() => {
    if (searching) {
      setSearchPage((current) => Math.min(Math.max(current, 1), memoryTotalPages));
    } else if (listData && !listWindowPending) {
      setListPage((current) => Math.min(Math.max(current, 1), memoryTotalPages));
    }
  }, [listData, listWindowPending, memoryTotalPages, searching]);

  const toggleSelected = (memoryId: string, selected?: boolean) => {
    if (!memoryId) return;
    setSelectedIds((current) => {
      const next = new Set(current);
      const shouldSelect = selected ?? !next.has(memoryId);
      if (shouldSelect) next.add(memoryId);
      else next.delete(memoryId);
      return next;
    });
  };

  const setManySelected = (memoryIds: readonly string[], selected: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const memoryId of memoryIds) {
        if (!memoryId) continue;
        if (selected) next.add(memoryId);
        else next.delete(memoryId);
      }
      return next;
    });
  };

  /** Select every memory currently loaded (the current 200-row window, or all search results). */
  const selectAllVisible = () => {
    setManySelected(
      loadedMemories.map((memory) => memory.id),
      true,
    );
  };

  const clearSelection = () => setSelectedIds(new Set());

  const removeFromSelection = (memoryIds: Iterable<string>) => {
    setSelectedIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const memoryId of memoryIds) {
        changed = next.delete(memoryId) || changed;
      }
      return changed ? next : current;
    });
  };

  /**
   * Mutation endpoints answer with the first list window. Store it for offset 0 and
   * refetch any other cached window so the visible page reflects the change.
   */
  const applyListMutationResult = (name: string, result: CharacterMemoryList) => {
    queryClient.setQueryData(memoryQueryKey(name, 0), result);
    void queryClient.invalidateQueries({
      predicate: (cached) =>
        cached.queryKey[0] === memoryQueryRoot(name)[0] && cached.queryKey[1] === name && cached.queryKey[2] !== 0,
      queryKey: memoryQueryRoot(name),
    });
    setListEnabledFor(name);
  };

  const ensureReady = async (): Promise<boolean> => {
    setMem0Checking(true);
    try {
      const status = await getMem0Status();
      if (status.status === "missing_dependency") {
        void query.refetch();
        return false;
      }
      if (status.status === "loading" || status.status === "not_started" || status.status === "error") {
        setMem0Task(status.task ?? null);
        setMem0LoadingMessage(
          status.modelCached ? t("character.memory.loadingModel") : t("character.memory.downloadingModel"),
        );
        setMem0LoadingOpen(true);
        let pollStatus = status;
        while (
          pollStatus.status === "loading" ||
          pollStatus.status === "not_started" ||
          pollStatus.status === "error"
        ) {
          const pollMs = pollStatus.task?.phase === "download" ? 1000 : pollStatus.modelCached ? 2000 : 3000;
          await new Promise((resolve) => setTimeout(resolve, pollMs));
          try {
            pollStatus = await getMem0Status();
            setMem0Task(pollStatus.task ?? null);
          } catch (error) {
            reportMem0StatusError(error);
            return false;
          }
        }
        setMem0LoadingOpen(false);
        if (pollStatus.status === "missing_dependency") {
          void query.refetch();
          return false;
        }
      }
      return true;
    } catch (error) {
      reportMem0StatusError(error);
      return false;
    } finally {
      setMem0Checking(false);
    }
  };

  const installDependency = async () => {
    if (!depError) {
      return;
    }
    setMemoryDepInstalling(true);
    setMemoryDepOpen(true);
    setMemoryDepTask(null);
    try {
      await installMissingRuntimeDependency(
        { moduleName: depError.moduleName },
        { onTaskUpdate: (task) => setMemoryDepTask(task) },
      );
      showToast({ kind: "success", title: t("character.memory.depInstalled") });
      setMemoryDepOpen(false);
      setMemoryDepTask(null);
      queryClient.setQueryData(memoryQueryKey(memoryName, listOffset), {
        agentId: memoryName || "user",
        count: 0,
        memories: [],
      });
      setMemoryDepInstalling(false);
      if (await ensureReady()) {
        setListEnabledFor(memoryName);
        void query.refetch();
      }
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.depInstallFailed"),
        title: t("character.memory.depInstallFailed"),
      });
    } finally {
      setMemoryDepInstalling(false);
    }
  };

  const syncUpdatedListIntoSearch = (result: CharacterMemoryList) => {
    setSearchData((current) => {
      if (!current) {
        return current;
      }
      const byId = new Map(result.memories.map((item) => [item.id, item]));
      const memories = current.memories.map((item) => byId.get(item.id) ?? item);
      return { ...current, memories };
    });
  };

  const addMutation = useMutation({
    mutationFn: () =>
      addAsCanon
        ? rememberCharacterMemory(memoryName, memoryInput, { kind: "canon", pinned: true })
        : rememberCharacterMemory(memoryName, memoryInput),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.add"),
      });
    },
    onSuccess(result) {
      setMemoryInput("");
      setAddAsCanon(false);
      setSearchInput("");
      setActiveSearchQuery("");
      setSearchData(null);
      setListPage(1);
      setSearchPage(1);
      applyListMutationResult(memoryName, result);
      showToast({ kind: "success", title: t("character.memory.add") });
    },
  });

  const pinMutation = useMutation({
    mutationFn: ({ memoryId, name, pinned }: { memoryId: string; name: string; pinned: boolean }) =>
      pinCharacterMemory({ memoryId, name, pinned }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.pin"),
      });
    },
    onSuccess(result, variables) {
      applyListMutationResult(variables.name, result);
      syncUpdatedListIntoSearch(result);
    },
  });

  const awakenMutation = useMutation({
    mutationFn: ({ memoryId, name }: { memoryId: string; name: string }) => awakenCharacterMemory({ memoryId, name }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.awaken"),
      });
    },
    onSuccess(result, variables) {
      applyListMutationResult(variables.name, result);
      syncUpdatedListIntoSearch(result);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ memoryId, name }: { memoryId: string; name: string }) => deleteCharacterMemory(name, memoryId),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.delete"),
      });
    },
    onSuccess(result, variables) {
      applyListMutationResult(variables.name, result);
      removeFromSelection([variables.memoryId]);
      setSearchData((current) => {
        if (!current) {
          return current;
        }
        const memories = current.memories.filter((memory) => memory.id !== variables.memoryId);
        return { ...current, count: memories.length, memories };
      });
    },
  });

  const deleteManyMutation = useMutation({
    mutationFn: ({ memoryIds, name }: { memoryIds: string[]; name: string }) =>
      deleteCharacterMemories(name, memoryIds),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.batchDeleteTitle"),
      });
    },
    onSuccess(result, variables) {
      applyListMutationResult(variables.name, result);
      const raw = result as CharacterMemoryList & { deleted?: unknown; failed?: unknown };
      // Prefer the backend's explicit report; the returned window may not contain every id.
      const reportedDeleted = Array.isArray(raw.deleted) ? raw.deleted.map(String) : null;
      const failedCount = Array.isArray(raw.failed) ? raw.failed.length : 0;
      const removedIds = new Set(reportedDeleted ?? variables.memoryIds);
      setSearchData((current) => {
        if (!current) {
          return current;
        }
        const memories = current.memories.filter((memory) => !removedIds.has(memory.id));
        return { ...current, count: memories.length, memories };
      });
      removeFromSelection(removedIds);
      showToast({
        kind: failedCount > 0 ? "info" : "success",
        message: failedCount > 0 ? t("character.memory.batchDeletePartial", { failed: failedCount }) : undefined,
        title: t("character.memory.batchDeleteSuccess", { count: removedIds.size }),
      });
    },
  });

  const runSearch = async (queryText: string) => {
    const trimmed = queryText.trim();
    if (!memoryName) return;
    if (!trimmed) {
      clearSearch();
      return;
    }
    if (!(await ensureReady())) return;
    try {
      await searchMutation.mutateAsync({ limit: MEMORY_SEARCH_LIMIT, name: memoryName, query: trimmed });
    } catch {
      // onError surfaces the failure via toast.
    }
  };

  const refresh = async () => {
    if (!memoryName) return;
    if (!(await ensureReady())) return;
    if (activeSearchQuery) {
      try {
        await searchMutation.mutateAsync({ limit: MEMORY_SEARCH_LIMIT, name: memoryName, query: activeSearchQuery });
      } catch {
        // onError surfaces the failure via toast.
      }
      return;
    }
    if (listEnabledFor !== memoryName) {
      // Enabling the query triggers the first window fetch.
      setListEnabledFor(memoryName);
      return;
    }
    void queryClient.invalidateQueries({ queryKey: memoryQueryRoot(memoryName) });
  };

  const add = async () => {
    if (!(await ensureReady())) return;
    addMutation.mutate();
  };

  const deleteMemory = async (input: { memoryId: string; name: string }) => {
    if (!(await ensureReady())) return;
    deleteMutation.mutate(input);
  };

  const deleteMemories = async (input: { memoryIds: string[]; name: string }) => {
    const memoryIds = Array.from(new Set(input.memoryIds.filter(Boolean)));
    if (!input.name || memoryIds.length === 0) return;
    if (!(await ensureReady())) return;
    try {
      await deleteManyMutation.mutateAsync({ memoryIds, name: input.name });
    } catch {
      // onError surfaces the failure via toast.
    }
  };

  /**
   * Export via the backend so the file covers every memory, not just the loaded window.
   * Selection wins; otherwise an active search exports its results; otherwise everything.
   */
  const exportMemories = async () => {
    if (!memoryName) return;
    const memoryIds =
      selectedIds.size > 0
        ? Array.from(selectedIds)
        : searching
          ? (searchData?.memories ?? []).map((memory) => memory.id).filter(Boolean)
          : undefined;
    if (memoryIds && memoryIds.length === 0) return;
    if (!(await ensureReady())) return;
    setExportPending(true);
    try {
      const exported = await exportCharacterMemories({
        labels: {
          canon: t("character.memory.clarity.canon"),
          createdAt: t("character.memory.exportCreatedAt"),
          detail: t("character.memory.exportDetail"),
          exportedAt: t("character.memory.exportExportedAt"),
          header: t("character.memory.exportHeader"),
          total: t("character.memory.exportTotal"),
        },
        memoryIds,
        name: memoryName,
      });
      const saved = await saveMemoriesTextFile(displayName || memoryName, exported.text);
      showToast({
        kind: "success",
        message: t("character.memory.exportSavedTo", { path: saved.path ?? saved.name }),
        title: t("character.memory.exportSuccess"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
        title: t("character.memory.exportFailed"),
      });
    } finally {
      setExportPending(false);
    }
  };

  const pinMemory = async (input: { memoryId: string; name: string; pinned: boolean }) => {
    if (!(await ensureReady())) return;
    pinMutation.mutate(input);
  };

  const awakenMemory = async (input: { memoryId: string; name: string }) => {
    if (!(await ensureReady())) return;
    awakenMutation.mutate(input);
  };

  function clearSearch() {
    if (activeSearchQuery) {
      setSelectedIds(new Set());
    }
    setSearchInput("");
    setActiveSearchQuery("");
    setSearchData(null);
    setSearchPage(1);
  }

  return {
    add,
    addAsCanon,
    addPending: addMutation.isPending,
    awakenMemory,
    awakenPending: awakenMutation.isPending,
    closeDependencyDialog: () => {
      if (!memoryDepInstalling) {
        setMemoryDepOpen(false);
        setMemoryDepTask(null);
      }
    },
    closeLoadingDialog: () => setMem0LoadingOpen(false),
    activeSearchQuery,
    clearSearch,
    clearSelection,
    data: pagedData,
    deleteMemories,
    deleteMemory,
    deleteManyPending: deleteManyMutation.isPending,
    deletePending: deleteMutation.isPending,
    depError,
    depInstalling: memoryDepInstalling,
    dependencyDialogOpen: memoryDepOpen,
    dependencyTask: memoryDepTask,
    error: searchMutation.error ?? query.error,
    ensureReady,
    exportMemories,
    exportPending,
    installDependency,
    isChecking: mem0Checking,
    isError: query.isError || searchMutation.isError || !!depError,
    isFetched: query.isFetched || Boolean(searchData),
    isFetching: query.isFetching || searchMutation.isPending,
    isLoading: query.isLoading || (!searching && listWindowPending),
    loadedCount: loadedMemories.length,
    loadingDialogOpen: mem0LoadingOpen,
    loadingMessage: mem0LoadingMessage,
    loadingTask: mem0Task,
    memoryInput,
    memoryPage,
    memoryTotalPages,
    pinMemory,
    pinPending: pinMutation.isPending,
    refresh,
    search: () => runSearch(searchInput),
    searchInput,
    searchPending: searchMutation.isPending,
    selectAllVisible,
    selectedIds,
    setAddAsCanon,
    setManySelected,
    setMemoryInput,
    setMemoryPage,
    setSearchInput,
    toggleSelected,
    totalVisibleCount: totalCount,
  };
}
