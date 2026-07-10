import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RotateCw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { backgroundsQueryKey, listBackgrounds } from "../../entities/background/repository";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { effectsQueryKey, listEffects } from "../../entities/effect/repository";
import { installMissingRuntimeDependency, launchChat } from "../../entities/chat/repository";
import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import {
  getTemplateSession,
  listTemplates,
  saveTemplateSession,
  templatesQueryKey,
} from "../../entities/template/repository";
import { ChatInitializationDialog } from "../chat-startup/ChatInitializationDialog";
import { useChatInitialization } from "../chat-startup/useChatInitialization";
import { useChatLaunchGuard } from "../chat-startup/useChatLaunchGuard";
import { TRANSPARENT_BACKGROUND_NAME } from "../../shared/constants";
import { showChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import type { ChatLaunchPayload, ChatSnapshot, TemplateLaunchSession } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  QueryErrorState,
  Select,
  TextInput,
  useToast,
} from "../../shared/ui";
// Shared page layout classes (.page, .section, .form-grid, .field-row) come from shared/theme/settings-base.css (imported in main.tsx)
import "./ChatLauncherPage.css";

export function ChatLauncherPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const templatesQuery = useQuery({ queryFn: listTemplates, queryKey: templatesQueryKey });
  const effectsQuery = useQuery({ queryFn: listEffects, queryKey: effectsQueryKey });
  const sessionQuery = useQuery({
    queryFn: getTemplateSession,
    queryKey: [...templatesQueryKey, "session"],
  });
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const { refreshRuntimeStatus, runtimeLaunchDisabled, updateRuntimeStatusFromSnapshot } = useChatLaunchGuard();
  const {
    closeInitialization,
    initializationError,
    initializationOpen,
    initializationPending,
    initializationTask,
    runChatInitialization,
  } = useChatInitialization();
  const characters = charactersQuery.data ?? [];
  const backgrounds = backgroundsQuery.data ?? [];
  const effects = Array.isArray(effectsQuery.data) ? effectsQuery.data : [];
  const templates = templatesQuery.data ?? [];
  const launchSession = sessionQuery.data;
  const sessionFetched = sessionQuery.isFetched;
  const appConfig = configQuery.data;
  const [templateId, setTemplateId] = useState("");
  const [backgroundName, setBackgroundName] = useState(TRANSPARENT_BACKGROUND_NAME);
  const [selectedEffects, setSelectedEffects] = useState<string[]>([]);
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [historyPath, setHistoryPath] = useState("");
  const [initSpritePath, setInitSpritePath] = useState("");
  const [useCg, setUseCg] = useState(false);
  const [quickRestartOpen, setQuickRestartOpen] = useState(false);
  const [sessionRestored, setSessionRestored] = useState(false);

  const selectedTemplate = templates.find((template) => template.id === templateId) ?? templates[0];
  const activeTemplateId = selectedTemplate?.id ?? "";
  const backgroundOptions = useMemo(() => {
    const names = backgrounds.map((background) => background.name);
    return names.includes(TRANSPARENT_BACKGROUND_NAME) ? names : [...names, TRANSPARENT_BACKGROUND_NAME];
  }, [backgrounds]);
  const failedQuery = [charactersQuery, backgroundsQuery, templatesQuery, sessionQuery, configQuery].find(
    (query) => query.isError,
  );
  const isLoadingLaunchData = [charactersQuery, backgroundsQuery, templatesQuery, sessionQuery, configQuery].some(
    (query) => query.isLoading,
  );

  useEffect(() => {
    if (!templateId && templates[0]) {
      setTemplateId(templates[0].id);
    }
    if (!backgroundName || !backgroundOptions.includes(backgroundName)) {
      setBackgroundName(TRANSPARENT_BACKGROUND_NAME);
    }
    if (!sessionRestored && !selectedCharacters.length && characters[0]) {
      setSelectedCharacters([characters[0].name]);
    }
  }, [
    backgroundName,
    backgroundOptions,
    characters,
    selectedCharacters.length,
    sessionRestored,
    templateId,
    templates,
  ]);

  useEffect(() => {
    if (!sessionFetched || sessionRestored) {
      return;
    }
    if (launchSession?.templateFileDropdown && !templates.length) {
      return;
    }
    setSessionRestored(true);
    if (!launchSession) {
      return;
    }
    const restoredTemplate =
      templates.find((template) => template.id === launchSession.templateFileDropdown) ??
      templates.find((template) => template.name === launchSession.filenameStub);
    if (restoredTemplate) {
      setTemplateId(restoredTemplate.id);
    }
    setBackgroundName(launchSession.background || TRANSPARENT_BACKGROUND_NAME);
    setSelectedEffects(Array.isArray(launchSession.effectNames) ? launchSession.effectNames : []);
    setSelectedCharacters(Array.isArray(launchSession.selectedCharacters) ? launchSession.selectedCharacters : []);
    setHistoryPath(launchSession.historyPath || "");
    setInitSpritePath(launchSession.initSpritePath || "");
    setUseCg(launchSession.useCg ?? false);
  }, [launchSession, sessionFetched, sessionRestored, templates]);

  const buildSession = (): TemplateLaunchSession => ({
    background: backgroundName,
    effectNames: selectedEffects,
    filenameStub: selectedTemplate?.name ?? "",
    historyPath: historyPath.trim(),
    initSpritePath: initSpritePath.trim(),
    maxDialogItems: launchSession?.maxDialogItems ?? 0,
    maxSpeechChars: launchSession?.maxSpeechChars ?? 0,
    roomId: launchSession?.roomId ?? "",
    scenario: selectedTemplate?.scenario ?? "",
    selectedCharacters,
    system: selectedTemplate?.system ?? "",
    templateFileDropdown: activeTemplateId,
    useCg,
    useChoice: launchSession?.useChoice ?? true,
    useCot: launchSession?.useCot ?? false,
    useEffect: launchSession?.useEffect ?? true,
    useNarration: launchSession?.useNarration ?? true,
    useStat: launchSession?.useStat ?? true,
    useTranslation: launchSession?.useTranslation ?? true,
    voiceLanguage: launchSession?.voiceLanguage || appConfig?.system_config.voice_language || "ja",
  });

  const handleRuntimeDependencyError = async (snapshot: ChatSnapshot) => {
    const dependencyError = snapshot.runtimeDependencyError;
    if (!dependencyError) {
      return false;
    }
    const shouldInstall = window.confirm(
      t("runtimeDeps.installConfirm", {
        module: dependencyError.moduleName,
        package: dependencyError.packageName,
      }),
    );
    if (!shouldInstall) {
      showToast({ kind: "error", message: snapshot.dialogText, title: t("launch.toast.failed") });
      return true;
    }
    try {
      const result = await installMissingRuntimeDependency({ moduleName: dependencyError.moduleName });
      showToast({
        kind: "success",
        message: result.message || t("runtimeDeps.installSucceeded"),
        title: t("runtimeDeps.installTitle"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("runtimeDeps.installFailed"),
        title: t("runtimeDeps.installFailed"),
      });
    }
    return true;
  };

  const launchMutation = useMutation({
    mutationFn: async (payload: ChatLaunchPayload) => {
      return runChatInitialization(async (options) => {
        const session = buildSession();
        await saveTemplateSession(session);
        queryClient.setQueryData([...templatesQueryKey, "session"], session);
        return launchChat(payload, options);
      });
    },
    onError(error) {
      void refreshRuntimeStatus();
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("launch.toast.failed"),
      });
    },
    onSuccess(snapshot) {
      void updateRuntimeStatusFromSnapshot(snapshot);
      if (snapshot.runtimeDependencyError) {
        void handleRuntimeDependencyError(snapshot);
        return;
      }
      showToast({
        kind: "success",
        message: snapshot.statusMessage || snapshot.dialogText,
        title: t("launch.toast.started"),
      });
      void showChatSurface({ navigate, snapshot });
    },
  });

  const ready = Boolean(activeTemplateId && backgroundName);
  const submitLaunch = (resetHistory: boolean) => {
    if (runtimeLaunchDisabled) {
      return;
    }
    if (!ready || !selectedTemplate) {
      showToast({ kind: "error", message: t("launch.emptyBody"), title: t("launch.toast.failed") });
      return;
    }
    launchMutation.mutate({
      backgroundName,
      characters: selectedCharacters,
      effectNames: selectedEffects.length ? selectedEffects : undefined,
      historyPath: historyPath.trim(),
      initSpritePath: initSpritePath.trim(),
      resetHistory,
      roomId: launchSession?.roomId ?? "",
      scenario: selectedTemplate.scenario ?? "",
      system: selectedTemplate.system ?? "",
      templateId: activeTemplateId,
      templateName: selectedTemplate.name,
      useCg,
    });
  };

  return (
    <div className="page launch-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("launch.title")}</h1>
        </div>
        <div className="page__actions">
          <AsyncButton
            disabled={runtimeLaunchDisabled || initializationPending}
            icon={<Play aria-hidden className="button__icon" />}
            loading={launchMutation.isPending}
            onClick={() => submitLaunch(false)}
            variant="primary"
          >
            {t("launch.start")}
          </AsyncButton>
          <Button
            disabled={runtimeLaunchDisabled || initializationPending}
            icon={<RotateCw aria-hidden className="button__icon" />}
            onClick={() => {
              if (launchMutation.isPending) {
                return;
              }
              if (!ready) {
                submitLaunch(false);
                return;
              }
              setQuickRestartOpen(true);
            }}
            variant="ghost"
          >
            {t("template.action.quickRestart")}
          </Button>
        </div>
      </header>

      {failedQuery ? (
        <QueryErrorState
          error={failedQuery.error}
          onRetry={() => void failedQuery.refetch()}
          retryLabel={t("common.retry")}
          title={t("common.operationFailed")}
        />
      ) : isLoadingLaunchData ? (
        <EmptyState title={t("template.loading")} />
      ) : !templates.length ? (
        <EmptyState title={t("launch.emptyTitle")} body={t("launch.emptyBody")} />
      ) : (
        <section className="section launch-page__panel">
          <div className="form-grid form-grid--two launch-page__grid">
            <label className="field-row">
              <span className="field-row__label">{t("launch.template")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("launch.template")}
                  onChange={(event) => setTemplateId(event.target.value)}
                  value={activeTemplateId}
                >
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.name}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("launch.background")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("launch.background")}
                  onChange={(event) => setBackgroundName(event.target.value)}
                  value={backgroundName}
                >
                  {backgroundOptions.map((name) => (
                    <option key={name} value={name}>
                      {name === TRANSPARENT_BACKGROUND_NAME ? t("template.transparentBackground") : name}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("launch.character")}</span>
              <span className="field-row__control">
                <Select
                  multiple
                  onChange={(event) =>
                    setSelectedCharacters(Array.from(event.currentTarget.selectedOptions).map((item) => item.value))
                  }
                  value={selectedCharacters}
                >
                  {characters.map((character) => (
                    <option key={character.name} value={character.name}>
                      {character.name}
                    </option>
                  ))}
                </Select>
                <span className="field-row__help">{t("launch.historyHelp")}</span>
              </span>
            </label>
            {effects.length > 0 ? (
              <label className="field-row">
                <span className="field-row__label">{t("template.field.effectName")}</span>
                <span className="field-row__control">
                  <Select
                    multiple
                    onChange={(event) =>
                      setSelectedEffects(Array.from(event.currentTarget.selectedOptions).map((item) => item.value))
                    }
                    value={selectedEffects}
                  >
                    {effects.map((effect) => (
                      <option key={effect.name} value={effect.name}>
                        {effect.name}
                      </option>
                    ))}
                  </Select>
                </span>
              </label>
            ) : null}
            <label className="field-row">
              <span className="field-row__label">{t("template.field.initSprite")}</span>
              <span className="field-row__control">
                <FilePicker
                  acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                  onChange={(event) => setInitSpritePath(event.target.value)}
                  onPathChange={setInitSpritePath}
                  pickLabel={t("common.chooseFile")}
                  pickerTitle={t("template.field.initSprite")}
                  readOnly={false}
                  value={initSpritePath}
                />
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("launch.history")}</span>
              <span className="field-row__control">
                <FilePicker
                  acceptedExtensions={[".json"]}
                  onChange={(event) => setHistoryPath(event.target.value)}
                  onPathChange={setHistoryPath}
                  pickLabel={t("common.chooseFile")}
                  pickerTitle={t("launch.history")}
                  placeholder={t("launch.historyPlaceholder")}
                  readOnly={false}
                  value={historyPath}
                />
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("template.field.useCg")}</span>
              <span className="field-row__control">
                <input checked={useCg} onChange={(event) => setUseCg(event.target.checked)} type="checkbox" />
              </span>
            </label>
          </div>
        </section>
      )}
      <AlertDialog
        body={t("template.quickRestart.body")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("template.action.quickRestart")}
        onCancel={() => setQuickRestartOpen(false)}
        onConfirm={() => {
          setQuickRestartOpen(false);
          submitLaunch(true);
        }}
        open={quickRestartOpen}
        title={t("template.quickRestart.title")}
      />
      <ChatInitializationDialog
        error={initializationError}
        onClose={closeInitialization}
        open={initializationOpen}
        pending={initializationPending}
        task={initializationTask}
      />
    </div>
  );
}
