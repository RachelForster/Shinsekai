import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { conversationsQueryKey, listConversations, prepareConversation } from "../../entities/chat/repository";
import { extractNovelCast, saveNovelCasting } from "../../entities/novel/repository";
import { useI18n } from "../../shared/i18n";
import { formatPlatformError } from "../../shared/platform/errors";
import type { ConversationSummary } from "../../shared/platform/types";
import { Button } from "../../shared/ui";
import {
  CastMappingTable,
  bindingsToCastRows,
  candidatesToCastRows,
  rowsToCastBindings,
  type CastMappingRow,
} from "./CastMappingTable";

export function NovelConversationSettings({
  conversationId,
  conversation,
  onPendingChange,
}: {
  conversationId?: string;
  conversation?: ConversationSummary;
  onPendingChange?: (pending: boolean) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const listQuery = useQuery({
    queryKey: conversationsQueryKey,
    queryFn: listConversations,
    enabled: !conversation,
    staleTime: 0,
  });
  const current = conversation ?? listQuery.data?.find((item) => item.id === conversationId);
  const charactersQuery = useQuery({
    queryKey: charactersQueryKey,
    queryFn: listCharacters,
  });

  const [rows, setRows] = useState<CastMappingRow[]>(() => bindingsToCastRows(current?.castEntries));
  const [resolvedDocId, setResolvedDocId] = useState(() => current?.novelDocId ?? "");
  const [savedNotice, setSavedNotice] = useState(false);
  const [errorText, setErrorText] = useState("");

  useEffect(() => {
    if (!current?.id) return;
    if (current.novelDocId) {
      setResolvedDocId(current.novelDocId);
    }
    if (current.castEntries?.length) {
      setRows(bindingsToCastRows(current.castEntries));
      return;
    }
    let active = true;
    void prepareConversation(current.id)
      .then((launch) => {
        if (!active) return;
        if (launch.novelDocId) setResolvedDocId(launch.novelDocId);
        if (launch.castEntries?.length) {
          setRows(bindingsToCastRows(launch.castEntries));
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [current?.id, current?.novelDocId, current?.castEntries]);

  const extractMutation = useMutation({
    mutationFn: (docId: string) => extractNovelCast(docId),
    onSuccess(result) {
      setErrorText("");
      setSavedNotice(false);
      setRows(candidatesToCastRows(result.characters));
    },
    onError(error) {
      setErrorText(formatPlatformError(error, t));
    },
  });

  const saveMutation = useMutation({
    mutationFn: ({ id, bindings }: { id: string; bindings: ReturnType<typeof rowsToCastBindings> }) =>
      saveNovelCasting(id, bindings),
    onMutate() {
      setErrorText("");
      setSavedNotice(false);
      onPendingChange?.(true);
    },
    onSuccess(saved) {
      queryClient.setQueryData<ConversationSummary[]>(conversationsQueryKey, (items) =>
        items?.map((item) => (item.id === saved.id ? saved : item)),
      );
      queryClient.setQueryData<ConversationSummary | null>([...conversationsQueryKey, "current"], (item) =>
        item?.id === saved.id ? saved : item,
      );
      setSavedNotice(true);
    },
    onError(error) {
      setErrorText(formatPlatformError(error, t));
    },
    onSettled() {
      onPendingChange?.(false);
    },
  });

  const busy = extractMutation.isPending || saveMutation.isPending;

  return (
    <section className="section">
      <h2 className="section__title">{t("novel.settings.title")}</h2>
      <p className="section__description">{t("novel.settings.hint")}</p>
      {!conversation && listQuery.isPending ? <p role="status">{t("common.loading")}</p> : null}
      {errorText ? (
        <p className="novel-wizard__error" role="alert">
          {errorText}
        </p>
      ) : null}
      {savedNotice ? (
        <p className="story-generator-pass" role="status">
          {t("novel.settings.saved")}
        </p>
      ) : null}
      {current ? (
        <>
          {resolvedDocId ? (
            <div className="novel-wizard__actions">
              <Button
                disabled={busy}
                icon={<Sparkles aria-hidden className="button__icon" />}
                onClick={() => extractMutation.mutate(resolvedDocId)}
                type="button"
              >
                {extractMutation.isPending ? t("novel.wizard.extractingCast") : t("novel.wizard.extractCast")}
              </Button>
            </div>
          ) : (
            <p className="novel-wizard__hint">{t("novel.settings.missingDoc")}</p>
          )}
          <CastMappingTable
            characters={charactersQuery.data ?? []}
            disabled={busy}
            onChange={(next) => {
              setSavedNotice(false);
              setRows(next);
            }}
            rows={rows}
          />
          <div className="novel-wizard__actions">
            <Button
              disabled={busy}
              onClick={() => saveMutation.mutate({ id: current.id, bindings: rowsToCastBindings(rows) })}
              type="button"
              variant="primary"
            >
              {t("novel.settings.save")}
            </Button>
          </div>
        </>
      ) : null}
    </section>
  );
}
