import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatSnapshot, TaskProgressOptions, TaskSnapshot } from "../../shared/platform/types";

type ChatInitializationOperation<TResult> = (options: TaskProgressOptions<ChatSnapshot>) => Promise<TResult>;

export interface ChatInitializationService {
  closeInitialization: () => void;
  initializationError: string | null;
  initializationOpen: boolean;
  initializationPending: boolean;
  initializationTask: TaskSnapshot<ChatSnapshot> | null;
  runChatInitialization: <TResult>(operation: ChatInitializationOperation<TResult>) => Promise<TResult>;
}

function initializationErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return typeof error === "string" ? error : "";
}

export function useChatInitialization(): ChatInitializationService {
  const operationTokenRef = useRef(0);
  const runningRef = useRef(false);
  const [initializationError, setInitializationError] = useState<string | null>(null);
  const [initializationOpen, setInitializationOpen] = useState(false);
  const [initializationPending, setInitializationPending] = useState(false);
  const [initializationTask, setInitializationTask] = useState<TaskSnapshot<ChatSnapshot> | null>(null);

  useEffect(
    () => () => {
      operationTokenRef.current += 1;
      runningRef.current = false;
    },
    [],
  );

  const runChatInitialization = useCallback(async <TResult>(operation: ChatInitializationOperation<TResult>) => {
    if (runningRef.current) {
      throw new Error("Chat initialization is already running.");
    }
    const token = operationTokenRef.current + 1;
    operationTokenRef.current = token;
    runningRef.current = true;
    setInitializationError(null);
    setInitializationTask(null);
    setInitializationPending(true);
    setInitializationOpen(true);

    try {
      const snapshot = await operation({
        onTaskUpdate(task) {
          if (operationTokenRef.current === token) {
            setInitializationTask(task);
          }
        },
      });
      if (operationTokenRef.current === token) {
        runningRef.current = false;
        setInitializationPending(false);
        setInitializationOpen(false);
      }
      return snapshot;
    } catch (error) {
      if (operationTokenRef.current === token) {
        runningRef.current = false;
        setInitializationError(initializationErrorMessage(error));
        setInitializationPending(false);
        setInitializationOpen(true);
      }
      throw error;
    }
  }, []);

  const closeInitialization = useCallback(() => {
    if (!runningRef.current) {
      setInitializationOpen(false);
    }
  }, []);

  return {
    closeInitialization,
    initializationError,
    initializationOpen,
    initializationPending,
    initializationTask,
    runChatInitialization,
  };
}
