import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { EmptyState, QueryErrorState } from "../../shared/ui";

interface CharacterListPanelProps {
  characters: Character[];
  currentDraftName: string;
  error: unknown;
  isCreating: boolean;
  isError: boolean;
  isLoading: boolean;
  onRetry: () => void;
  onSelect: (name: string) => void;
}

export function CharacterListPanel({
  characters,
  currentDraftName,
  error,
  isCreating,
  isError,
  isLoading,
  onRetry,
  onSelect,
}: CharacterListPanelProps) {
  const { t } = useI18n();

  return (
    <aside className="entity-list">
      <div className="entity-list__header">
        <strong>{t("character.listTitle")}</strong>
        <span className="entity-list__meta">{characters.length}</span>
      </div>
      {isLoading ? <EmptyState title={t("character.loading")} /> : null}
      {isError ? (
        <QueryErrorState
          error={error}
          onRetry={onRetry}
          retryLabel={t("common.retry")}
          title={t("common.operationFailed")}
        />
      ) : null}
      {!isLoading && !isError && !characters.length ? (
        <EmptyState title={t("character.emptyTitle")} body={t("character.emptyBody")} />
      ) : null}
      {characters.map((character) => (
        <button
          aria-selected={!isCreating && character.name === currentDraftName}
          className="entity-list__item"
          key={character.name}
          onClick={() => onSelect(character.name)}
          type="button"
        >
          <span className="entity-list__primary">{character.name}</span>
          <span className="swatch" style={{ background: character.color }} />
        </button>
      ))}
    </aside>
  );
}
