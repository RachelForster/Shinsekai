import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteCharacterMemory,
  getMem0Status,
  listCharacterMemories,
  rememberCharacterMemory,
  searchCharacterMemories,
} from "../../entities/character/repository";
import { installMissingRuntimeDependency } from "../../entities/chat/repository";
import { useI18n } from "../../shared/i18n";
import type { TaskSnapshot } from "../../shared/platform/types";
import { useToast } from "../../shared/ui";

const memoryQueryKey = (name: string) => ["character-memories", name] as const;
const MEMORY_PAGE_SIZE = 8;
const MEMORY_SEARCH_LIMIT = 200;

interface UseCharacterMemoryControllerOptions {
  memoryName: string;
}

export function useCharacterMemoryController({ memoryName }: UseCharacterMemoryControllerOptions) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const [memoryInput, setMemoryInput] = useState("");
  const [memoryDepOpen, setMemoryDepOpen] = useState(false);
  const [memoryDepInstalling, setMemoryDepInstalling] = useState(false);
  const [memoryDepTask, setMemoryDepTask] = useState<TaskSnapshot | null>(null);
  const [mem0LoadingOpen, setMem0LoadingOpen] = useState(false);
  const [mem0LoadingMessage, setMem0LoadingMessage] = useState("");
  const [mem0Task, setMem0Task] = useState<TaskSnapshot | null>(null);
  const [mem0Checking, setMem0Checking] = useState(false);
  const [memoryPage, setMemoryPage] = useState(1);
  const [searchData, setSearchData] = useState<Awaited<ReturnType<typeof searchCharacterMemories>> | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearchQuery, setActiveSearchQuery] = useState("");

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
    enabled: false,
    queryFn: () => listCharacterMemories(memoryName),
    queryKey: memoryQueryKey(memoryName),
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
      setActiveSearchQuery(variables.query.trim());
      setSearchData(result);
      setMemoryPage(1);
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

  const visibleData = depError ? undefined : activeSearchQuery ? (searchData ?? undefined) : query.data;
  const memoryTotalPages = Math.max(1, Math.ceil((visibleData?.memories.length ?? 0) / MEMORY_PAGE_SIZE));
  const pagedData = useMemo(() => {
    if (!visibleData) {
      return undefined;
    }
    const startIndex = (memoryPage - 1) * MEMORY_PAGE_SIZE;
    return {
      ...visibleData,
      memories: visibleData.memories.slice(startIndex, startIndex + MEMORY_PAGE_SIZE),
    };
  }, [memoryPage, visibleData]);

  useEffect(() => {
    setSearchInput("");
    setActiveSearchQuery("");
    setSearchData(null);
    setMemoryPage(1);
  }, [memoryName]);

  useEffect(() => {
    setMemoryPage((current) => Math.min(Math.max(current, 1), memoryTotalPages));
  }, [memoryTotalPages]);

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
        const pollMs = status.modelCached ? 2000 : 3000;
        let pollStatus = status;
        while (
          pollStatus.status === "loading" ||
          pollStatus.status === "not_started" ||
          pollStatus.status === "error"
        ) {
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
        if (pollStatus.status === "error") {
          showToast({
            kind: "error",
            message: pollStatus.task?.errorUserMessage || pollStatus.message || t("character.memory.error"),
            title: t("common.operationFailed"),
          });
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
      queryClient.setQueryData(memoryQueryKey(memoryName), {
        agentId: memoryName || "user",
        count: 0,
        memories: [],
      });
      setMemoryDepInstalling(false);
      if (await ensureReady()) {
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

  const addMutation = useMutation({
    mutationFn: () => rememberCharacterMemory(memoryName, memoryInput),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.error"),
        title: t("character.memory.add"),
      });
    },
    onSuccess(result) {
      setMemoryInput("");
      setSearchInput("");
      setActiveSearchQuery("");
      setSearchData(null);
      setMemoryPage(1);
      queryClient.setQueryData(memoryQueryKey(memoryName), result);
      showToast({ kind: "success", title: t("character.memory.add") });
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
      queryClient.setQueryData(memoryQueryKey(variables.name), result);
      setSearchData((current) => {
        if (!current) {
          return current;
        }
        const memories = current.memories.filter((memory) => memory.id !== variables.memoryId);
        return { ...current, count: memories.length, memories };
      });
    },
  });

  const runSearch = async (queryText: string) => {
    const trimmed = queryText.trim();
    if (!memoryName) return;
    if (!trimmed) {
      setActiveSearchQuery("");
      setSearchData(null);
      setMemoryPage(1);
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
    void query.refetch();
  };

  const add = async () => {
    if (!(await ensureReady())) return;
    addMutation.mutate();
  };

  const deleteMemory = async (input: { memoryId: string; name: string }) => {
    if (!(await ensureReady())) return;
    deleteMutation.mutate(input);
  };

  const clearSearch = () => {
    setSearchInput("");
    setActiveSearchQuery("");
    setSearchData(null);
    setMemoryPage(1);
  };

  return {
    add,
    addPending: addMutation.isPending,
    closeDependencyDialog: () => {
      if (!memoryDepInstalling) {
        setMemoryDepOpen(false);
        setMemoryDepTask(null);
      }
    },
    closeLoadingDialog: () => setMem0LoadingOpen(false),
    activeSearchQuery,
    clearSearch,
    data: pagedData,
    deleteMemory,
    deletePending: deleteMutation.isPending,
    depError,
    depInstalling: memoryDepInstalling,
    dependencyDialogOpen: memoryDepOpen,
    dependencyTask: memoryDepTask,
    error: searchMutation.error ?? query.error,
    installDependency,
    isChecking: mem0Checking,
    isError: query.isError || searchMutation.isError || !!depError,
    isFetched: query.isFetched || Boolean(searchData),
    isFetching: query.isFetching || searchMutation.isPending,
    isLoading: query.isLoading,
    loadingDialogOpen: mem0LoadingOpen,
    loadingMessage: mem0LoadingMessage,
    loadingTask: mem0Task,
    memoryInput,
    memoryPage,
    memoryTotalPages,
    refresh,
    search: () => runSearch(searchInput),
    searchInput,
    searchPending: searchMutation.isPending,
    setMemoryInput,
    setMemoryPage,
    setSearchInput,
  };
}
