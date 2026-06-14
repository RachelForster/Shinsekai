import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RotateCw, Save, Sparkles, Users } from "lucide-react";

import { backgroundsQueryKey, listBackgrounds } from "../../entities/background/repository";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { installMissingRuntimeDependency, launchChat } from "../../entities/chat/repository";
import { configQueryKey, getAppConfig, saveSystemConfig } from "../../entities/config/repository";
import {
  generateTemplate,
  getTemplateSession,
  listTemplates,
  saveTemplate,
  saveTemplateSession,
  templatesQueryKey,
  type TemplateSummary,
} from "../../entities/template/repository";
import { DEFAULT_CHARACTER_COLOR, TRANSPARENT_BACKGROUND_NAME } from "../../shared/constants";
import { useI18n } from "../../shared/i18n";
import type { ChatSnapshot, TemplateLaunchSession } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  NumberInput,
  QueryErrorState,
  Select,
  Switch,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import "./TemplateEditorPage.css";

const voiceLanguages = [
  { labelKey: "system.asr.langJa", value: "ja" },
  { labelKey: "system.asr.langEn", value: "en" },
  { labelKey: "system.asr.langZh", value: "zh" },
  { labelKey: "system.asr.langYue", value: "yue" },
] as const;

type CharacterChipStyle = CSSProperties & {
  "--template-character-color"?: string;
};

function getCharacterChipStyle(color: string): CharacterChipStyle {
  return {
    "--template-character-color": color.trim() || DEFAULT_CHARACTER_COLOR,
  };
}

function composeContent(scenario: unknown, system: unknown) {
  return [String(scenario ?? "").trim(), String(system ?? "").trim()].filter(Boolean).join("\n\n");
}

function createTemplate(name: string): TemplateSummary {
  return {
    content: "",
    id: "",
    name,
    path: "",
    scenario: "",
    system: "",
    updatedAt: "",
  };
}

function normalizeTemplate(template: TemplateSummary): TemplateSummary {
  const scenario = template.scenario ?? (template.system ? "" : (template.content ?? ""));
  const system = template.system ?? (template.scenario ? (template.content ?? "") : "");
  return {
    ...template,
    content: composeContent(scenario, system),
    scenario,
    system,
  };
}

export function TemplateEditorPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const templatesQuery = useQuery({ queryFn: listTemplates, queryKey: templatesQueryKey });
  const sessionQuery = useQuery({
    queryFn: getTemplateSession,
    queryKey: [...templatesQueryKey, "session"],
  });
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const templates = templatesQuery.data ?? [];
  const isLoading = templatesQuery.isLoading;
  const launchSession = sessionQuery.data;
  const sessionFetched = sessionQuery.isFetched;
  const appConfig = configQuery.data;
  const characters = charactersQuery.data ?? [];
  const backgrounds = backgroundsQuery.data ?? [];
  const [selectedId, setSelectedId] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [sessionDraftActive, setSessionDraftActive] = useState(false);
  const [sessionRestored, setSessionRestored] = useState(false);
  const [draft, setDraft] = useState<TemplateSummary>(() => createTemplate(t("template.defaultName")));
  const [nameError, setNameError] = useState("");
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [selectedBackground, setSelectedBackground] = useState(TRANSPARENT_BACKGROUND_NAME);
  const [voiceLanguage, setVoiceLanguage] = useState("ja");
  const [useEffectPrompt, setUseEffectPrompt] = useState(true);
  const [useTranslation, setUseTranslation] = useState(true);
  const [useCg, setUseCg] = useState(false);
  const [useCot, setUseCot] = useState(false);
  const [useChoice, setUseChoice] = useState(true);
  const [useNarration, setUseNarration] = useState(true);
  const [useStat, setUseStat] = useState(true);
  const [maxSpeechChars, setMaxSpeechChars] = useState(0);
  const [maxDialogItems, setMaxDialogItems] = useState(0);
  const [initSpritePath, setInitSpritePath] = useState("");
  const [historyPath, setHistoryPath] = useState("");
  const [roomId, setRoomId] = useState("");
  const [systemExpanded, setSystemExpanded] = useState(false);
  const [quickRestartOpen, setQuickRestartOpen] = useState(false);
  const autoGenerateReadyRef = useRef(false);
  const suppressNextAutoGenerateRef = useRef(false);

  const selected = useMemo(
    () => (isCreating ? undefined : (templates.find((template) => template.id === selectedId) ?? templates[0])),
    [isCreating, selectedId, templates],
  );
  const backgroundOptions = useMemo(() => {
    const names = backgrounds.map((background) => background.name);
    return names.includes(TRANSPARENT_BACKGROUND_NAME) ? names : [...names, TRANSPARENT_BACKGROUND_NAME];
  }, [backgrounds]);
  const selectedCharacterNames = useMemo(() => new Set(selectedCharacters), [selectedCharacters]);
  const failedQuery = [templatesQuery, sessionQuery, configQuery, charactersQuery, backgroundsQuery].find(
    (query) => query.isError,
  );
  const templateSelectValue = !isCreating && !sessionDraftActive ? selectedId || selected?.id || "" : "";

  useEffect(() => {
    if (selected && !sessionDraftActive) {
      setSelectedId(selected.id);
      setDraft(normalizeTemplate(structuredClone(selected)));
      setNameError("");
    }
  }, [selected, sessionDraftActive]);

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
    setSessionDraftActive(true);
    setSelectedCharacters(Array.isArray(launchSession.selectedCharacters) ? launchSession.selectedCharacters : []);
    setSelectedBackground(launchSession.background || TRANSPARENT_BACKGROUND_NAME);
    setVoiceLanguage(launchSession.voiceLanguage || "ja");
    setUseEffectPrompt(launchSession.useEffect ?? true);
    setUseTranslation(launchSession.useTranslation ?? true);
    setUseCg(launchSession.useCg ?? false);
    setUseCot(launchSession.useCot ?? false);
    setUseChoice(launchSession.useChoice ?? true);
    setUseNarration(launchSession.useNarration ?? true);
    setUseStat(launchSession.useStat ?? true);
    setMaxSpeechChars(Number(launchSession.maxSpeechChars) || 0);
    setMaxDialogItems(Number(launchSession.maxDialogItems) || 0);
    setInitSpritePath(launchSession.initSpritePath || "");
    setHistoryPath(launchSession.historyPath || "");
    setRoomId(launchSession.roomId || "");
    const matchingTemplate = templates.find((template) => template.id === launchSession.templateFileDropdown);
    setSelectedId(matchingTemplate?.id ?? "");
    setDraft(
      normalizeTemplate({
        content: composeContent(launchSession.scenario, launchSession.system),
        id: matchingTemplate?.id ?? "",
        name: launchSession.filenameStub || matchingTemplate?.name || t("template.defaultName"),
        path: matchingTemplate?.path ?? "",
        scenario: launchSession.scenario,
        system: launchSession.system,
        updatedAt: matchingTemplate?.updatedAt ?? "",
      }),
    );
  }, [launchSession, sessionFetched, sessionRestored, t, templates]);

  useEffect(() => {
    if (!backgroundOptions.includes(selectedBackground)) {
      setSelectedBackground(TRANSPARENT_BACKGROUND_NAME);
    }
  }, [backgroundOptions, selectedBackground]);

  useEffect(() => {
    if (!sessionRestored || launchSession) {
      return;
    }
    const configuredLanguage = String(appConfig?.system_config.voice_language || "")
      .trim()
      .toLowerCase();
    const nextLanguage = voiceLanguages.some((option) => option.value === configuredLanguage)
      ? configuredLanguage
      : "ja";
    if (!configuredLanguage || nextLanguage === voiceLanguage) {
      return;
    }
    suppressNextAutoGenerateRef.current = true;
    setVoiceLanguage(nextLanguage);
  }, [appConfig, launchSession, sessionRestored, voiceLanguage]);

  const updateDraft = (patch: Partial<TemplateSummary>) => {
    setDraft((current) => {
      const next = { ...current, ...patch };
      const scenario = String(next.scenario ?? "");
      const system = String(next.system ?? "");
      return { ...next, content: composeContent(scenario, system) };
    });
  };

  const validateName = () => {
    if (!draft.name.trim()) {
      setNameError(t("template.validation.nameRequired"));
      return false;
    }
    setNameError("");
    return true;
  };

  const buildTemplate = () => {
    const name = draft.name.trim();
    const scenario = String(draft.scenario ?? "");
    const system = String(draft.system ?? "");
    return {
      ...draft,
      content: composeContent(scenario, system),
      name,
      scenario,
      system,
    };
  };

  const buildLaunchSession = (): TemplateLaunchSession => ({
    background: selectedBackground,
    filenameStub: draft.name.trim(),
    historyPath: historyPath.trim(),
    initSpritePath: initSpritePath.trim(),
    maxDialogItems,
    maxSpeechChars,
    roomId: roomId.trim(),
    scenario: String(draft.scenario ?? ""),
    selectedCharacters,
    system: String(draft.system ?? ""),
    templateFileDropdown: selectedId,
    useCg,
    useChoice,
    useCot,
    useEffect: useEffectPrompt,
    useNarration,
    useStat,
    useTranslation,
    voiceLanguage,
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
      showToast({ kind: "error", message: snapshot.dialogText, title: t("template.error.launchFailed") });
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

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!validateName()) {
        throw new Error(t("template.validation.nameRequired"));
      }
      return saveTemplate(buildTemplate());
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("template.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(template) {
      queryClient.invalidateQueries({ queryKey: templatesQueryKey });
      const normalized = normalizeTemplate(template);
      setIsCreating(false);
      setSessionDraftActive(false);
      setDraft(normalized);
      setSelectedId(normalized.id);
      showToast({ kind: "success", title: t("template.toast.saved") });
    },
  });

  const voiceLanguageMutation = useMutation({
    mutationFn: async (language: string) => {
      const config = await getAppConfig();
      return saveSystemConfig({
        ...config.system_config,
        voice_language: language,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("system.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
  });

  const generateMutation = useMutation({
    mutationFn: async (_options?: { silent?: boolean }) => {
      return generateTemplate({
        backgroundName: selectedBackground,
        characters: selectedCharacters,
        maxDialogItems,
        maxSpeechChars,
        name: draft.name.trim(),
        scenario: String(draft.scenario ?? ""),
        useCg,
        useChoice,
        useCot,
        useEffect: useEffectPrompt,
        useNarration,
        useStat,
        useTranslation,
        voiceLanguage,
      });
    },
    onError(error, options) {
      if (options?.silent) {
        return;
      }
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("template.error.generateFallback"),
        title: t("template.error.generateFailed"),
      });
    },
    onSuccess(template, options) {
      const normalized = normalizeTemplate(template);
      setIsCreating(true);
      setSessionDraftActive(true);
      setDraft(normalized);
      if (!options?.silent) {
        showToast({ kind: "success", message: template.generationMessage, title: t("template.toast.generated") });
      }
    },
  });

  useEffect(() => {
    if (!sessionRestored) {
      return;
    }
    if (!autoGenerateReadyRef.current) {
      autoGenerateReadyRef.current = true;
      return;
    }
    if (suppressNextAutoGenerateRef.current) {
      suppressNextAutoGenerateRef.current = false;
      return;
    }
    if (generateMutation.isPending) {
      return;
    }
    const timer = window.setTimeout(() => generateMutation.mutate({ silent: true }), 160);
    return () => window.clearTimeout(timer);
  }, [
    selectedCharacters,
    selectedBackground,
    voiceLanguage,
    useEffectPrompt,
    useTranslation,
    useCg,
    useCot,
    useChoice,
    useNarration,
    useStat,
    maxSpeechChars,
    maxDialogItems,
    sessionRestored,
  ]);

  const launchMutation = useMutation({
    mutationFn: async ({ resetHistory }: { resetHistory: boolean }) => {
      const template = buildTemplate();
      const session = buildLaunchSession();
      await saveTemplateSession(session);
      queryClient.setQueryData([...templatesQueryKey, "session"], session);
      const snapshot = await launchChat({
        backgroundName: selectedBackground,
        characters: selectedCharacters,
        historyPath: historyPath.trim(),
        initSpritePath: initSpritePath.trim(),
        roomId: roomId.trim(),
        resetHistory,
        scenario: String(template.scenario ?? ""),
        system: String(template.system ?? ""),
        templateName: template.name,
        templateId: template.id,
        useCg,
      });
      return { snapshot, template };
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("template.error.launchFailed"),
        title: t("template.error.launchFailed"),
      });
    },
    onSuccess({ snapshot, template }) {
      const normalized = normalizeTemplate(template);
      setSessionDraftActive(true);
      setDraft(normalized);
      if (snapshot.runtimeDependencyError) {
        void handleRuntimeDependencyError(snapshot);
        return;
      }
      showToast({ kind: "success", message: snapshot.dialogText, title: t("template.toast.launched") });
    },
  });

  const toggleCharacter = (name: string, checked: boolean) => {
    setSelectedCharacters((current) =>
      checked ? [...new Set([...current, name])] : current.filter((item) => item !== name),
    );
  };

  const handleTemplateSelect = (nextId: string) => {
    if (!nextId) {
      return;
    }
    setSessionDraftActive(false);
    setIsCreating(false);
    setSelectedId(nextId);
  };

  const handleVoiceLanguageChange = (nextLanguage: string) => {
    if (nextLanguage === voiceLanguage) {
      return;
    }
    setVoiceLanguage(nextLanguage);
    voiceLanguageMutation.mutate(nextLanguage);
  };

  const handleGenerateTemplate = () => {
    if (!selectedBackground) {
      showToast({
        kind: "error",
        message: t("template.validation.backgroundRequired"),
        title: t("template.mode.generate"),
      });
      return;
    }
    if (!selectedCharacters.length) {
      showToast({
        kind: "error",
        message: t("template.validation.charactersRequired"),
        title: t("template.mode.generate"),
      });
      return;
    }
    generateMutation.mutate({ silent: false });
  };

  const templateOptions = [
    { key: "effect", label: t("template.field.useEffect"), setValue: setUseEffectPrompt, value: useEffectPrompt },
    {
      key: "translation",
      label: t("template.field.useTranslation"),
      setValue: setUseTranslation,
      value: useTranslation,
    },
    { key: "cg", label: t("template.field.useCg"), setValue: setUseCg, value: useCg },
    { key: "cot", label: t("template.field.useCot"), setValue: setUseCot, value: useCot },
    { key: "choice", label: t("template.field.useChoice"), setValue: setUseChoice, value: useChoice },
    { key: "narration", label: t("template.field.useNarration"), setValue: setUseNarration, value: useNarration },
    { key: "stat", label: t("template.field.useStat"), setValue: setUseStat, value: useStat },
  ];

  return (
    <div className="page template-page">
      <header className="template-page__topbar">
        <label className="template-topbar-field template-topbar-field--select">
          <span className="template-topbar-field__label">{t("template.section.load")}</span>
          <Select
            disabled={!templates.length}
            onChange={(event) => handleTemplateSelect(event.target.value)}
            value={templateSelectValue}
          >
            <option value="">
              {sessionDraftActive || isCreating ? draft.name || t("template.defaultName") : t("template.section.load")}
            </option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="template-topbar-field">
          <span className="template-topbar-field__label">{t("template.field.templateName")}</span>
          <span className="input-group">
            <TextInput
              className={nameError ? "input--error" : ""}
              onChange={(event) => {
                updateDraft({ name: event.target.value });
                if (event.target.value.trim()) {
                  setNameError("");
                }
              }}
              value={draft.name}
            />
            <AsyncButton
              className="template-save-button"
              icon={<Save aria-hidden className="button__icon" />}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {t("common.save")}
            </AsyncButton>
          </span>
          {nameError ? <span className="field-error">{nameError}</span> : null}
        </label>
      </header>

      {isLoading || failedQuery || (!templates.length && !failedQuery) ? (
        <div className="template-page__status">
          {isLoading ? <EmptyState title={t("template.loading")} /> : null}
          {failedQuery ? (
            <QueryErrorState
              error={failedQuery.error}
              onRetry={() => void failedQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!isLoading && !failedQuery && !templates.length ? (
            <EmptyState title={t("template.emptyTitle")} body={t("template.emptyBody")} />
          ) : null}
        </div>
      ) : null}

      <div className="template-workbench">
        <section className="template-workbench__main">
          <section className="template-panel template-panel--characters">
            <div className="template-character-picker">
              <div className="template-character-picker__header">
                <span className="template-panel__label">{t("template.field.characters")}</span>
                <Button
                  disabled={!characters.length}
                  icon={<Users aria-hidden className="button__icon" />}
                  onClick={() => setSelectedCharacters(characters.map((character) => character.name))}
                  variant="ghost"
                >
                  {t("template.action.selectAllCharacters")}
                </Button>
              </div>
              <div aria-label={t("template.field.characters")} className="template-character-grid" role="group">
                {characters.map((character) => {
                  const isSelected = selectedCharacterNames.has(character.name);
                  return (
                    <button
                      aria-pressed={isSelected}
                      className={`template-character-card${isSelected ? " template-character-card--selected" : ""}`}
                      key={character.name}
                      onClick={() => toggleCharacter(character.name, !isSelected)}
                      style={getCharacterChipStyle(character.color)}
                      title={character.name}
                      type="button"
                    >
                      <span aria-hidden className="template-character-card__dot" />
                      <span className="template-character-card__name">{character.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>

          <section className="template-panel template-panel--scenario">
            <label className="template-stack-field">
              <span className="template-panel__label">{t("template.field.scenario")}</span>
              <TextArea
                className="template-scenario-textarea"
                onChange={(event) => updateDraft({ scenario: event.target.value })}
                rows={7}
                value={draft.scenario ?? ""}
              />
            </label>
          </section>

          <section className={`template-panel template-panel--system${systemExpanded ? " is-expanded" : ""}`}>
            <button
              aria-expanded={systemExpanded}
              className="template-system-toggle"
              onClick={() => setSystemExpanded((current) => !current)}
              type="button"
            >
              <span>{t("template.section.system")}</span>
              <span aria-hidden className="section-toggle__indicator" />
            </button>
            {systemExpanded ? (
              <label className="template-stack-field template-stack-field--system">
                <span className="template-panel__label">{t("template.field.system")}</span>
                <TextArea
                  className="template-system-textarea"
                  onChange={(event) => updateDraft({ system: event.target.value })}
                  rows={12}
                  value={draft.system ?? ""}
                />
              </label>
            ) : null}
          </section>
        </section>

        <aside className="template-options-panel">
          <div className="template-options-panel__header">
            <h2 className="template-options-panel__title">{t("template.section.generate")}</h2>
            <AsyncButton
              className="template-generate-button"
              icon={<Sparkles aria-hidden className="button__icon" />}
              loading={generateMutation.isPending}
              onClick={handleGenerateTemplate}
              variant="primary"
            >
              {t("template.mode.generate")}
            </AsyncButton>
          </div>

          <label className="template-side-field">
            <span className="template-side-field__label">{t("template.field.background")}</span>
            <Select onChange={(event) => setSelectedBackground(event.target.value)} value={selectedBackground}>
              {backgroundOptions.map((name) => (
                <option key={name} value={name}>
                  {name === TRANSPARENT_BACKGROUND_NAME ? t("template.transparentBackground") : name}
                </option>
              ))}
            </Select>
          </label>

          <div className="template-side-field">
            <span className="template-side-field__label">{t("template.field.voiceLanguage")}</span>
            <div className="template-language-segments" role="group">
              {voiceLanguages.map((option) => (
                <button
                  aria-pressed={voiceLanguage === option.value}
                  className={`template-language-segment${
                    voiceLanguage === option.value ? " template-language-segment--active" : ""
                  }`}
                  key={option.value}
                  onClick={() => handleVoiceLanguageChange(option.value)}
                  type="button"
                >
                  {t(option.labelKey)}
                </button>
              ))}
            </div>
          </div>

          <p className="template-options-panel__hint">{t("template.optionHelp")}</p>

          <div className="template-option-list">
            {templateOptions.map((option) => (
              <label className="template-toggle-row" key={option.key}>
                <span>{option.label}</span>
                <Switch checked={option.value} onChange={(e) => option.setValue(e.target.checked)} />
              </label>
            ))}
          </div>

          <div className="template-number-grid">
            <label className="template-side-field">
              <span className="template-side-field__label">{t("template.field.maxSpeechChars")}</span>
              <NumberInput
                max={500000}
                min={0}
                onChange={(event) => setMaxSpeechChars(Number.parseInt(event.target.value, 10) || 0)}
                step={10}
                value={maxSpeechChars}
              />
            </label>
            <label className="template-side-field">
              <span className="template-side-field__label">{t("template.field.maxDialogItems")}</span>
              <NumberInput
                max={500}
                min={0}
                onChange={(event) => setMaxDialogItems(Number.parseInt(event.target.value, 10) || 0)}
                value={maxDialogItems}
              />
            </label>
          </div>

          <div className="template-runtime-fields">
            <label className="template-side-field">
              <span className="template-side-field__label">{t("template.field.initSprite")}</span>
              <FilePicker
                acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                onChange={(event) => setInitSpritePath(event.target.value)}
                onPathChange={setInitSpritePath}
                pickLabel={t("common.chooseFile")}
                pickerTitle={t("template.field.initSprite")}
                readOnly={false}
                value={initSpritePath}
              />
            </label>
            <label className="template-side-field">
              <span className="template-side-field__label">{t("template.field.historyFile")}</span>
              <TextInput onChange={(event) => setHistoryPath(event.target.value)} value={historyPath} />
            </label>
          </div>
        </aside>
      </div>

      <footer className="template-page__footer">
        <AsyncButton
          icon={<Play aria-hidden className="button__icon" />}
          loading={launchMutation.isPending}
          onClick={() => launchMutation.mutate({ resetHistory: false })}
          variant="primary"
        >
          {t("template.action.launch")}
        </AsyncButton>
        <Button
          icon={<RotateCw aria-hidden className="button__icon" />}
          onClick={() => setQuickRestartOpen(true)}
          variant="ghost"
        >
          {t("template.action.quickRestart")}
        </Button>
      </footer>

      <AlertDialog
        body={t("template.quickRestart.body")}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("template.action.quickRestart")}
        onCancel={() => setQuickRestartOpen(false)}
        onConfirm={() => {
          setQuickRestartOpen(false);
          launchMutation.mutate({ resetHistory: true });
        }}
        open={quickRestartOpen}
        title={t("template.quickRestart.title")}
      />
    </div>
  );
}
