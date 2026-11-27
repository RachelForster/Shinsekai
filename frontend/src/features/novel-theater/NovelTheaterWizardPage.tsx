import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, Trash2, Upload } from "lucide-react";
import { backgroundsQueryKey, listBackgrounds } from "../../entities/background/repository";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { chatQueryKey, conversationsQueryKey, launchChat } from "../../entities/chat/repository";
import {
  deleteNovelDocument,
  extractNovelCast,
  getNovelDocument,
  importNovelDocument,
  listNovelDocuments,
  novelDocumentsQueryKey,
  prepareNovelLaunchPayload,
} from "../../entities/novel/repository";
import { resolveConversationTitle } from "../../entities/chat/conversationTitle";
import { useI18n } from "../../shared/i18n";
import { formatPlatformError } from "../../shared/platform/errors";
import type { ChatSnapshot, MediaSelectionMode, NovelCastBindingInput } from "../../shared/platform/types";
import { Button, IconButton, Select, TextInput } from "../../shared/ui";
import type { ChatInitializationService } from "../chat-startup/useChatInitialization";
import { useMobileAccessPreference } from "../mobile-access/useMobileAccessPreference";
import { CastMappingTable, candidatesToCastRows, rowsToCastBindings, type CastMappingRow } from "./CastMappingTable";
import "./NovelTheaterWizardPage.css";

const MAX_TOC_PREVIEW_ITEMS = 30;

export function NovelTheaterWizardPage({
  conversationTitle = "",
  initializationService,
  onLaunchStarted,
  onLaunched,
}: {
  conversationTitle?: string;
  initializationService?: ChatInitializationService;
  onLaunchStarted?: () => void;
  onLaunched?: (snapshot: ChatSnapshot) => Promise<void> | void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [mobileAccessEnabled] = useMobileAccessPreference();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [castRows, setCastRows] = useState<CastMappingRow[]>([]);
  const [titleOverride, setTitleOverride] = useState(conversationTitle);
  const [startChapterIndex, setStartChapterIndex] = useState(0);
  const [backgroundName, setBackgroundName] = useState("");
  const [mediaSelectionMode, setMediaSelectionMode] = useState<MediaSelectionMode>("indexed");
  const [errorText, setErrorText] = useState("");
  const [launching, setLaunching] = useState(false);

  const documentsQuery = useQuery({
    queryKey: novelDocumentsQueryKey,
    queryFn: listNovelDocuments,
  });
  const charactersQuery = useQuery({
    queryKey: charactersQueryKey,
    queryFn: listCharacters,
  });
  const backgroundsQuery = useQuery({
    queryKey: backgroundsQueryKey,
    queryFn: listBackgrounds,
  });

  const activeDocId = selectedDocId || documentsQuery.data?.[0]?.manifest.docId || "";
  const docDetailQuery = useQuery({
    queryKey: [...novelDocumentsQueryKey, activeDocId],
    queryFn: () => getNovelDocument(activeDocId),
    enabled: Boolean(activeDocId),
  });
  const selectedSummary = documentsQuery.data?.find((item) => item.manifest.docId === activeDocId);
  const activeDetail = docDetailQuery.data ?? selectedSummary;
  const activeChapters = activeDetail?.chapters ?? [];

  const importMutation = useMutation({
    mutationFn: (file: File) => importNovelDocument(file),
    onSuccess(detail) {
      setErrorText("");
      setSelectedDocId(detail.manifest.docId);
      setStartChapterIndex(0);
      setCastRows([]);
      if (!titleOverride.trim()) {
        setTitleOverride(detail.manifest.title);
      }
      queryClient.setQueryData([...novelDocumentsQueryKey, detail.manifest.docId], detail);
      void queryClient.invalidateQueries({ queryKey: novelDocumentsQueryKey });
    },
    onError(error) {
      setErrorText(formatPlatformError(error, t));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (docId: string) => deleteNovelDocument(docId),
    onSuccess(result) {
      setErrorText("");
      if (selectedDocId === result.docId) {
        setSelectedDocId("");
        setCastRows([]);
      }
      void queryClient.invalidateQueries({ queryKey: novelDocumentsQueryKey });
    },
    onError(error) {
      setErrorText(formatPlatformError(error, t));
    },
  });

  const extractMutation = useMutation({
    mutationFn: (docId: string) => extractNovelCast(docId),
    onSuccess(result) {
      setErrorText("");
      setCastRows(candidatesToCastRows(result.characters));
    },
    onError(error) {
      setErrorText(formatPlatformError(error, t));
    },
  });

  const boundCharactersSummary = useMemo(() => {
    const names = [...new Set(castRows.map((row) => row.targetCharacter.trim()).filter(Boolean))];
    return names.join(" · ");
  }, [castRows]);

  const handleLaunch = async (bindingsOverride?: NovelCastBindingInput[]) => {
    if (!activeDocId || launching) return;
    setErrorText("");
    setLaunching(true);
    try {
      const bindings = bindingsOverride ?? rowsToCastBindings(castRows);
      const payload = await prepareNovelLaunchPayload({
        docId: activeDocId,
        casting: bindings,
        startChapterIndex,
        backgroundName,
        conversationTitle: resolveConversationTitle(titleOverride) || undefined,
        mediaSelectionMode,
        enableMobileAccess: mobileAccessEnabled,
      });
      const finalPayload = { ...payload, enableMobileAccess: mobileAccessEnabled };
      const snapshot = initializationService
        ? await initializationService.runChatInitialization((options) => launchChat(finalPayload, options))
        : await launchChat(finalPayload);
      queryClient.setQueryData(chatQueryKey, snapshot);
      void queryClient.invalidateQueries({ queryKey: conversationsQueryKey });
      if (onLaunched) {
        await onLaunched(snapshot);
      } else {
        onLaunchStarted?.();
      }
    } catch (error) {
      setErrorText(formatPlatformError(error, t));
    } finally {
      setLaunching(false);
    }
  };

  return (
    <section className="section novel-wizard" aria-label={t("novel.wizard.title")}>
      <div>
        <h2 className="section__title">{t("novel.wizard.title")}</h2>
        <p className="section__description">{t("novel.wizard.subtitle")}</p>
      </div>

      <div className="novel-wizard__steps" role="tablist" aria-label={t("novel.wizard.title")}>
        <span className="novel-wizard__step" data-active={step === 1 ? "true" : undefined}>
          {t("novel.wizard.step1")}
        </span>
        <span className="novel-wizard__step" data-active={step === 2 ? "true" : undefined}>
          {t("novel.wizard.step2")}
        </span>
        <span className="novel-wizard__step" data-active={step === 3 ? "true" : undefined}>
          {t("novel.wizard.step3")}
        </span>
      </div>

      {errorText ? (
        <p className="novel-wizard__error" role="alert">
          {errorText}
        </p>
      ) : null}

      {step === 1 ? (
        <>
          <div className="novel-wizard__upload-box">
            <input
              accept=".txt,.md,.markdown,.pdf"
              aria-label={t("novel.wizard.upload")}
              className="novel-wizard__upload-input"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) importMutation.mutate(file);
              }}
              ref={fileInputRef}
              type="file"
            />
            <Button
              disabled={importMutation.isPending}
              icon={<Upload aria-hidden className="button__icon" />}
              onClick={() => fileInputRef.current?.click()}
              type="button"
              variant="primary"
            >
              {importMutation.isPending ? t("novel.wizard.uploading") : t("novel.wizard.upload")}
            </Button>
            <p className="novel-wizard__hint">{t("novel.wizard.uploadHint")}</p>
          </div>

          <h3>{t("novel.wizard.libraryTitle")}</h3>
          {documentsQuery.isPending ? <p role="status">{t("common.loading")}</p> : null}
          {!documentsQuery.isPending && (documentsQuery.data?.length ?? 0) === 0 ? (
            <p className="novel-wizard__hint">{t("novel.wizard.libraryEmpty")}</p>
          ) : (
            <div className="novel-wizard__doc-list">
              {documentsQuery.data?.map((doc) => {
                const isSelected = doc.manifest.docId === activeDocId;
                return (
                  <article
                    className="novel-wizard__doc-card"
                    data-selected={isSelected ? "true" : undefined}
                    key={doc.manifest.docId}
                  >
                    <div className="novel-wizard__doc-head">
                      <button
                        className="novel-wizard__doc-select"
                        onClick={() => {
                          setSelectedDocId(doc.manifest.docId);
                          setStartChapterIndex(0);
                        }}
                        type="button"
                      >
                        {doc.manifest.title}
                      </button>
                      <IconButton
                        disabled={deleteMutation.isPending}
                        label={`${t("novel.wizard.deleteDoc")} ${doc.manifest.title}`}
                        onClick={() => deleteMutation.mutate(doc.manifest.docId)}
                      >
                        <Trash2 aria-hidden className="icon-button__icon" />
                      </IconButton>
                    </div>
                    <div className="novel-wizard__doc-meta">
                      {t("novel.wizard.docMeta", {
                        chapters: doc.manifest.totalChapters,
                        chunks: doc.manifest.totalChunks,
                        chars: doc.manifest.totalChars,
                      })}
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          {activeDetail ? (
            <div>
              <h3>{t("novel.wizard.tocPreview")}</h3>
              <div className="novel-wizard__toc">
                {activeChapters.slice(0, MAX_TOC_PREVIEW_ITEMS).map((chap) => (
                  <div className="novel-wizard__toc-item" key={`toc-${chap.index}`}>
                    <span>{chap.title}</span>
                    <span>
                      {t("novel.drawer.chapterRange", {
                        start: chap.startChunkIndex + 1,
                        end: Math.max(chap.startChunkIndex + 1, chap.startChunkIndex + Math.max(1, chap.chunkCount)),
                      })}
                    </span>
                  </div>
                ))}
                {activeChapters.length > MAX_TOC_PREVIEW_ITEMS ? (
                  <p className="novel-wizard__hint">
                    {t("novel.wizard.tocMore", { count: activeChapters.length - MAX_TOC_PREVIEW_ITEMS })}
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}

          <div className="novel-wizard__actions">
            <Button disabled={!activeDocId || launching} onClick={() => setStep(2)} type="button" variant="primary">
              {t("novel.wizard.next")}
            </Button>
            <Button
              disabled={!activeDocId || launching}
              onClick={() => {
                setCastRows([]);
                void handleLaunch([]);
              }}
              type="button"
            >
              {launching ? t("novel.wizard.starting") : t("novel.wizard.skipCastingDirect")}
            </Button>
          </div>
        </>
      ) : null}

      {step === 2 ? (
        <>
          <div className="novel-wizard__toolbar">
            <div>
              <h3>{t("novel.wizard.castTitle")}</h3>
              <p className="novel-wizard__hint">
                {activeDetail ? `${t("novel.wizard.selectedDoc", { title: activeDetail.manifest.title })} · ` : ""}
                {t("novel.wizard.castHint")}
              </p>
            </div>
            <Button
              disabled={!activeDocId || extractMutation.isPending}
              icon={<Sparkles aria-hidden className="button__icon" />}
              onClick={() => extractMutation.mutate(activeDocId)}
              type="button"
            >
              {extractMutation.isPending ? t("novel.wizard.extractingCast") : t("novel.wizard.extractCast")}
            </Button>
          </div>

          <CastMappingTable
            characters={charactersQuery.data ?? []}
            disabled={launching}
            onChange={setCastRows}
            rows={castRows}
          />

          <div className="novel-wizard__actions">
            <Button disabled={launching} onClick={() => setStep(1)} type="button">
              {t("novel.wizard.back")}
            </Button>
            <Button
              disabled={launching}
              onClick={() => {
                setCastRows([]);
                setStep(3);
              }}
              type="button"
            >
              {t("novel.wizard.skipCasting")}
            </Button>
            <Button
              disabled={launching}
              onClick={() => {
                setCastRows([]);
                void handleLaunch([]);
              }}
              type="button"
            >
              {launching ? t("novel.wizard.starting") : t("novel.wizard.skipCastingDirect")}
            </Button>
            <Button disabled={launching} onClick={() => setStep(3)} type="button" variant="primary">
              {t("novel.wizard.next")}
            </Button>
          </div>
        </>
      ) : null}

      {step === 3 ? (
        <>
          <h3>{t("novel.wizard.stageTitle")}</h3>
          <div className="form-grid form-grid--two">
            <label className="field-row">
              <span className="field-row__label">{t("novel.wizard.titleLabel")}</span>
              <span className="field-row__control">
                <TextInput
                  aria-label={t("novel.wizard.titleLabel")}
                  disabled={launching}
                  maxLength={120}
                  onChange={(event) => setTitleOverride(event.target.value)}
                  placeholder={t("novel.wizard.titlePlaceholder")}
                  value={titleOverride}
                />
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("novel.wizard.startChapterLabel")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("novel.wizard.startChapterLabel")}
                  disabled={launching || activeChapters.length === 0}
                  onChange={(event) => setStartChapterIndex(Number(event.target.value) || 0)}
                  value={String(startChapterIndex)}
                >
                  {activeChapters.map((chap) => (
                    <option key={`start-chap-${chap.index}`} value={String(chap.index)}>
                      {chap.title}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("novel.wizard.backgroundLabel")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("novel.wizard.backgroundLabel")}
                  disabled={launching}
                  onChange={(event) => setBackgroundName(event.target.value)}
                  value={backgroundName}
                >
                  <option value="">{t("novel.wizard.backgroundNone")}</option>
                  {backgroundsQuery.data?.map((bg) => (
                    <option key={bg.name} value={bg.name}>
                      {bg.name}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("novel.wizard.mediaModeLabel")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("novel.wizard.mediaModeLabel")}
                  disabled={launching}
                  onChange={(event) => setMediaSelectionMode(event.target.value as MediaSelectionMode)}
                  value={mediaSelectionMode}
                >
                  <option value="indexed">{t("novel.wizard.mediaModeIndexed")}</option>
                  <option value="semantic">{t("novel.wizard.mediaModeSemantic")}</option>
                </Select>
              </span>
            </label>
          </div>

          <p className="novel-wizard__hint">
            {boundCharactersSummary
              ? t("novel.wizard.boundSummary", { names: boundCharactersSummary })
              : t("novel.wizard.pureDialogSummary")}
          </p>

          <div className="novel-wizard__actions">
            <Button disabled={launching} onClick={() => setStep(2)} type="button">
              {t("novel.wizard.back")}
            </Button>
            <Button
              disabled={!activeDocId || launching}
              onClick={() => void handleLaunch()}
              type="button"
              variant="primary"
            >
              {launching ? t("novel.wizard.starting") : t("novel.wizard.start")}
            </Button>
          </div>
        </>
      ) : null}
    </section>
  );
}
