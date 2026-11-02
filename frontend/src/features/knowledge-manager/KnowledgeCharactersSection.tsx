import { useI18n } from "../../shared/i18n";
import { EmptyState, AsyncButton, QueryErrorState } from "../../shared/ui";
import { type useKnowledgeController } from "./useKnowledgeController";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "lucide-react";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { listKnowledgeBindingNames } from "../../entities/knowledge/repository";
import { CharacterPicker } from "../template-editor/CharacterPicker";

export function KnowledgeCharactersSection({
  controller: c,
  disabled = false,
  embedded = false,
}: {
  controller: ReturnType<typeof useKnowledgeController>;
  disabled?: boolean;
  embedded?: boolean;
}) {
  const { t } = useI18n();
  const Heading = embedded ? "h3" : "h2";
  return (
    <section
      id="knowledge-characters"
      className={embedded ? "knowledge-section__group" : "section page-section-anchor"}
      aria-labelledby="knowledge-characters-title"
    >
      <div className="section__header">
        <Heading id="knowledge-characters-title" className="section__title">
          {t("knowledge.boundCharacters")}
        </Heading>
      </div>
      {!c.selectedKnowledge ? (
        <EmptyState title={t("knowledge.selectKnowledge")} body={t("knowledge.selectKnowledgeHint")} />
      ) : (
        <>
          <KnowledgeSubscriptions controller={c} disabled={disabled} key={c.selectedKnowledge} />
          {c.bindingError ? (
            <p className="inline-status" role="alert">
              {t("common.operationFailed")}: {c.bindingError.message}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

function KnowledgeSubscriptions({
  controller,
  disabled,
}: {
  controller: ReturnType<typeof useKnowledgeController>;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const [edits, setEdits] = useState<Record<string, boolean>>({});
  const characters = useQuery({ queryKey: charactersQueryKey, queryFn: listCharacters });
  const bindings = useQuery({
    queryKey: ["knowledge", "binding-names", controller.selectedKnowledge],
    queryFn: () => listKnowledgeBindingNames(controller.selectedKnowledge),
    retry: false,
  });
  const available = characters.data ?? [];
  const bound = new Set(bindings.data?.characterNames ?? []);
  const pending = disabled || controller.bindingPending || controller.writePending;
  const changes = available.filter((c) => edits[c.name] !== undefined && edits[c.name] !== bound.has(c.name));
  const error = characters.error || bindings.error;

  return (
    <div>
      {error ? (
        <QueryErrorState
          error={error}
          title={t("common.operationFailed")}
          onRetry={() => {
            void characters.refetch();
            void bindings.refetch();
          }}
          retryLabel={t("common.retry")}
        />
      ) : characters.isPending || bindings.isPending ? (
        <p className="inline-status" role="status">
          {t("common.loading")}
        </p>
      ) : !available.length ? (
        <p className="inline-status">{t("knowledge.noAvailableCharacters")}</p>
      ) : (
        <div className="knowledge-subscription-picker">
          <CharacterPicker
            characters={available}
            selected={available
              .filter((character) => edits[character.name] ?? bound.has(character.name))
              .map((character) => character.name)}
            disabled={pending}
            onChange={(names) => {
              const selected = new Set(names);
              setEdits((previous) => {
                const next = { ...previous };
                for (const character of available) {
                  if (selected.has(character.name) !== (previous[character.name] ?? bound.has(character.name))) {
                    next[character.name] = selected.has(character.name);
                  }
                }
                return next;
              });
            }}
          />
          <AsyncButton
            className="knowledge-subscription-picker__save"
            disabled={pending || !changes.length}
            loading={controller.batchBindingPending}
            onClick={async () => {
              const add = changes.filter((c) => edits[c.name]).map((c) => c.name);
              const remove = changes.filter((c) => !edits[c.name]).map((c) => c.name);
              if (await controller.saveBindings(add, remove)) setEdits({});
            }}
            icon={<Link aria-hidden className="button__icon" />}
          >
            {t("knowledge.saveBindings")}
          </AsyncButton>
        </div>
      )}
    </div>
  );
}
