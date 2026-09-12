import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelStoryGeneration,
  getStoryGeneration,
  getStoryPreview,
  regenerateStoryGeneration,
  startStoryGeneration,
  storyLibraryQueryKey,
} from "../../../entities/story/repository";
import type {
  StoryGenerationInput,
  StoryGenerationStage,
  StoryGenerationTask,
  TaskSnapshot,
} from "../../../shared/platform/types";

const storageKey = "shinsekai.story-generation.task";
function savedTask() {
  try {
    return localStorage.getItem(storageKey) ?? sessionStorage.getItem(storageKey) ?? "";
  } catch {
    return "";
  }
}

export function useStoryGeneration() {
  const client = useQueryClient();
  const [id, setId] = useState(savedTask);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const operation = useRef(false);
  const activeId = useRef(id);
  const taskQuery = useQuery({
    queryKey: ["story-generation", id],
    queryFn: () => getStoryGeneration(id),
    enabled: !!id,
    refetchInterval: (query) => (!["succeeded", "cancelled"].includes(query.state.data?.status ?? "") ? 1500 : false),
  });
  const task = taskQuery.data ?? null;
  useEffect(() => {
    if (task?.status === "succeeded") void client.invalidateQueries({ queryKey: storyLibraryQueryKey });
  }, [client, task?.id, task?.status]);
  const previewQuery = useQuery({
    queryKey: ["story-preview", id, task?.updatedAt, task?.completedStages, task?.artifactHashes],
    queryFn: () => getStoryPreview(id),
    enabled: !!id && !!task?.completedStages.length,
  });
  const track = (next: StoryGenerationTask) => {
    void client.cancelQueries({ queryKey: ["story-generation", next.id], exact: true });
    activeId.current = next.id;
    setId(next.id);
    client.setQueryData<StoryGenerationTask>(["story-generation", next.id], (current) =>
      current && current.updatedAt > next.updatedAt ? current : next,
    );
    if (next.status === "succeeded") void client.invalidateQueries({ queryKey: storyLibraryQueryKey });
    try {
      localStorage.setItem(storageKey, next.id);
      sessionStorage.removeItem(storageKey);
    } catch {
      /* In-memory state remains available. */
    }
  };
  const onTaskUpdate = (update: TaskSnapshot<StoryGenerationTask>) => {
    const next = update.generationTask ?? update.result;
    if (next) track(next);
  };
  const run = async (action: () => Promise<StoryGenerationTask>) => {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    try {
      track(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      if (activeId.current) await client.invalidateQueries({ queryKey: ["story-generation", activeId.current] });
    } finally {
      setBusy(false);
      operation.current = false;
    }
  };
  const pending = busy || task?.status === "running" || task?.status === "queued";
  return {
    task,
    preview: previewQuery.data,
    pending,
    error:
      (!pending && task?.status !== "cancelled" ? error : "") ||
      (pending || task?.status === "cancelled" ? "" : task?.error?.message) ||
      taskQuery.error?.message ||
      previewQuery.error?.message ||
      "",
    start: (input: StoryGenerationInput) => {
      if (pending) return;
      activeId.current = "";
      return run(() => startStoryGeneration(input, { onTaskUpdate }));
    },
    regenerate: (stage: StoryGenerationStage) => run(() => regenerateStoryGeneration(id, stage, { onTaskUpdate })),
    cancel: async () => {
      try {
        track(await cancelStoryGeneration(id));
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    },
  };
}
