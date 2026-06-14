import { Brain, RefreshCw } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { CharacterMemoryList } from "../../shared/platform/types";
import { AsyncButton, Button, EmptyState, QueryErrorState, TextInput } from "../../shared/ui";

interface CharacterMemorySectionProps {
  addPending: boolean;
  data?: CharacterMemoryList;
  deletePending: boolean;
  error: unknown;
  id?: string;
  isError: boolean;
  isFetching: boolean;
  isFetched: boolean;
  isLoading: boolean;
  memoryInput: string;
  memoryName: string;
  onAddMemory: () => void;
  onDeleteMemory: (memory: { id: string; memory: string }) => void;
  onMemoryInputChange: (value: string) => void;
  onRefresh: () => void;
}

export function CharacterMemorySection({
  addPending,
  data,
  deletePending,
  error,
  id,
  isError,
  isFetched,
  isFetching,
  isLoading,
  memoryInput,
  memoryName,
  onAddMemory,
  onDeleteMemory,
  onMemoryInputChange,
  onRefresh,
}: CharacterMemorySectionProps) {
  const { t } = useI18n();

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.memory.section")}</h2>
        <div className="page__actions">
          <span className="entity-list__meta">{data ? t("character.memory.count", { count: data.count }) : ""}</span>
          <Button
            disabled={!memoryName || isFetching}
            icon={<RefreshCw aria-hidden className="button__icon" />}
            onClick={onRefresh}
            variant="ghost"
          >
            {t("character.memory.refresh")}
          </Button>
        </div>
      </div>
      {!memoryName ? <EmptyState title={t("character.memory.nameRequired")} /> : null}
      {memoryName && isLoading ? <EmptyState title={t("character.memory.loading")} /> : null}
      {memoryName && isError ? (
        <QueryErrorState
          body={t("character.memory.error")}
          error={error}
          onRetry={onRefresh}
          retryLabel={t("common.retry")}
          title={t("common.operationFailed")}
        />
      ) : null}
      {memoryName && isFetched && !isLoading && !isError && !data?.memories.length ? (
        <EmptyState title={t("character.memory.empty")} />
      ) : null}
      {data?.memories.length ? (
        <div className="memory-table">
          {data.memories.map((memory) => (
            <div className="memory-row" key={memory.id || memory.memory}>
              <Brain aria-hidden className="asset-row__icon" />
              <div className="memory-row__content">
                <strong>{memory.memory}</strong>
                <span>{memory.id}</span>
              </div>
              <AsyncButton
                disabled={!memory.id}
                loading={deletePending}
                onClick={() => {
                  if (!memory.id) {
                    return;
                  }
                  onDeleteMemory({ id: memory.id, memory: memory.memory });
                }}
                variant="ghost"
              >
                {t("character.memory.delete")}
              </AsyncButton>
            </div>
          ))}
        </div>
      ) : null}
      <div className="memory-add-row">
        <TextInput
          disabled={!memoryName}
          onChange={(event) => onMemoryInputChange(event.target.value)}
          placeholder={t("character.memory.placeholder")}
          value={memoryInput}
        />
        <AsyncButton disabled={!memoryName || !memoryInput.trim()} loading={addPending} onClick={onAddMemory}>
          {t("character.memory.add")}
        </AsyncButton>
      </div>
    </section>
  );
}
