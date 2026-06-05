import { RefreshCw } from "lucide-react";
import { useEffect } from "react";

import {
  desktopRestartErrorMessage,
  isDesktopBridgeConnectionError,
  writeDesktopRestartDebugLog,
} from "../desktop/desktopApi";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";

interface QueryErrorStateProps {
  body?: string;
  error: unknown;
  onRetry?: () => void;
  retryLabel: string;
  title: string;
}

function errorMessage(error: unknown, fallback = "") {
  return error instanceof Error ? error.message : fallback;
}

export function QueryErrorState({ body, error, onRetry, retryLabel, title }: QueryErrorStateProps) {
  useEffect(() => {
    if (!isDesktopBridgeConnectionError(error)) {
      return;
    }
    void writeDesktopRestartDebugLog(
      `QueryErrorState displayed bridge error title=${title} body=${body ?? ""} error=${desktopRestartErrorMessage(
        error,
      )}`,
    );
  }, [body, error, title]);

  return (
    <EmptyState
      action={
        onRetry ? (
          <Button icon={<RefreshCw aria-hidden className="button__icon" />} onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : null
      }
      body={errorMessage(error, body) || body}
      title={title}
    />
  );
}
