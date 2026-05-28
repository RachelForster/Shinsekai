import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Play, RotateCw, Save } from "lucide-react";

import { backgroundsQueryKey, listBackgrounds } from "../../entities/background/repository";
import { charactersQueryKey, listCharacters } from "../../entities/character/repository";
import { launchChat } from "../../entities/chat/repository";
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
import { useI18n } from "../../shared/i18n";
import type { TemplateLaunchSession } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  NumberInput,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";

const TRANSPARENT_BACKGROUND = "透明场景";

const voiceLanguages = [
  { label: "日本語", value: "ja" },
  { label: "English", value: "en" },
  { label: "中文", value: "zh" },
  { label: "粤语", value: "yue" },
] as const;

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
  const { data: templates = [], isLoading } = useQuery({ queryFn: listTemplates, queryKey: templatesQueryKey });
  const { data: launchSession, isFetched: sessionFetched } = useQuery({
    queryFn: getTemplateSession,
    queryKey: [...templatesQueryKey, "session"],
  });
  const { data: appConfig } = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const { data: characters = [] } = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const { data: backgrounds = [] } = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const [selectedId, setSelectedId] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [sessionDraftActive, setSessionDraftActive] = useState(false);
  const [sessionRestored, setSessionRestored] = useState(false);
  const [draft, setDraft] = useState<TemplateSummary>(() => createTemplate(t("template.defaultName")));
  const [nameError, setNameError] = useState("");
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [selectedBackground, setSelectedBackground] = useState(TRANSPARENT_BACKGROUND);
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
    return names.includes(TRANSPARENT_BACKGROUND) ? names : [...names, TRANSPARENT_BACKGROUND];
  }, [backgrounds]);

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
    setSelectedBackground(launchSession.background || TRANSPARENT_BACKGROUND);
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
      setSelectedBackground(TRANSPARENT_BACKGROUND);
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
      showToast({ kind: "success", message: snapshot.dialogText, title: t("template.toast.launched") });
    },
  });

  const toggleCharacter = (name: string, checked: boolean) => {
    setSelectedCharacters((current) =>
      checked ? [...new Set([...current, name])] : current.filter((item) => item !== name),
    );
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
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("template.title")}</h1>
          <p className="page__description">{t("template.description")}</p>
        </div>
      </header>

      <div className="settings-grid settings-grid--split">
        <aside className="entity-list">
          <div className="entity-list__header">
            <strong>{t("template.section.load")}</strong>
            <span className="entity-list__meta">{templates.length}</span>
          </div>
          {isLoading ? <EmptyState title={t("template.loading")} /> : null}
          {!isLoading && !templates.length ? (
            <EmptyState title={t("template.emptyTitle")} body={t("template.emptyBody")} />
          ) : null}
          {templates.map((template) => (
            <button
              aria-selected={template.id === draft.id}
              className="entity-list__item"
              key={template.id}
              onClick={() => {
                setSessionDraftActive(false);
                setIsCreating(false);
                setSelectedId(template.id);
              }}
              type="button"
            >
              <span className="entity-list__primary">{template.name}</span>
              <span className="entity-list__meta">{template.updatedAt}</span>
            </button>
          ))}
        </aside>

        <section className="settings-grid">
          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("template.section.generate")}</h2>
            </div>
            <div className="form-grid form-grid--two">
              <label className="field-row">
                <span className="field-row__label">{t("template.field.background")}</span>
                <span className="field-row__control">
                  <Select onChange={(event) => setSelectedBackground(event.target.value)} value={selectedBackground}>
                    {backgroundOptions.map((name) => (
                      <option key={name} value={name}>
                        {name === TRANSPARENT_BACKGROUND ? t("template.transparentBackground") : name}
                      </option>
                    ))}
                  </Select>
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("template.field.voiceLanguage")}</span>
                <span className="field-row__control">
                  <Select
                    onChange={(event) => {
                      const next = event.target.value;
                      setVoiceLanguage(next);
                      voiceLanguageMutation.mutate(next);
                    }}
                    value={voiceLanguage}
                  >
                    {voiceLanguages.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("template.field.maxSpeechChars")}</span>
                <span className="field-row__control">
                  <NumberInput
                    max={500000}
                    min={0}
                    onChange={(event) => setMaxSpeechChars(Number.parseInt(event.target.value, 10) || 0)}
                    step={10}
                    value={maxSpeechChars}
                  />
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("template.field.maxDialogItems")}</span>
                <span className="field-row__control">
                  <NumberInput
                    max={500}
                    min={0}
                    onChange={(event) => setMaxDialogItems(Number.parseInt(event.target.value, 10) || 0)}
                    value={maxDialogItems}
                  />
                </span>
              </label>
            </div>

            <div className="template-option-grid">
              {templateOptions.map((option) => (
                <fieldset className="radio-row" key={option.key}>
                  <legend>{option.label}</legend>
                  <label>
                    <input
                      checked={option.value}
                      name={`template-${option.key}`}
                      onChange={() => option.setValue(true)}
                      type="radio"
                    />
                    <span>{t("common.yes")}</span>
                  </label>
                  <label>
                    <input
                      checked={!option.value}
                      name={`template-${option.key}`}
                      onChange={() => option.setValue(false)}
                      type="radio"
                    />
                    <span>{t("common.no")}</span>
                  </label>
                </fieldset>
              ))}
            </div>

            <div className="character-check-grid">
              {characters.map((character) => (
                <label className="check-row" key={character.name}>
                  <input
                    checked={selectedCharacters.includes(character.name)}
                    onChange={(event) => toggleCharacter(character.name, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{character.name}</span>
                </label>
              ))}
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("template.section.scenario")}</h2>
            </div>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("template.field.scenario")}</span>
              <span className="field-row__control">
                <TextArea
                  onChange={(event) => updateDraft({ scenario: event.target.value })}
                  rows={7}
                  value={draft.scenario ?? ""}
                />
              </span>
            </label>
          </section>

          <section className="section">
            <div className="section__header">
              <button
                aria-expanded={systemExpanded}
                className="section-toggle"
                onClick={() => setSystemExpanded((current) => !current)}
                type="button"
              >
                {systemExpanded ? (
                  <ChevronDown aria-hidden className="button__icon" />
                ) : (
                  <ChevronRight aria-hidden className="button__icon" />
                )}
                <span>{t("template.section.system")}</span>
              </button>
            </div>
            {systemExpanded ? (
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("template.field.system")}</span>
                <span className="field-row__control">
                  <TextArea
                    onChange={(event) => updateDraft({ system: event.target.value })}
                    rows={12}
                    value={draft.system ?? ""}
                  />
                </span>
              </label>
            ) : null}
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("template.section.run")}</h2>
            </div>
            <div className="form-grid">
              <label className="field-row">
                <span className="field-row__label">{t("template.field.templateName")}</span>
                <span className="field-row__control">
                  <div className="input-group">
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
                      icon={<Save aria-hidden className="button__icon" />}
                      loading={saveMutation.isPending}
                      onClick={() => saveMutation.mutate()}
                    >
                      {t("common.save")}
                    </AsyncButton>
                  </div>
                  {nameError ? <span className="field-error">{nameError}</span> : null}
                </span>
              </label>
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
                <span className="field-row__label">{t("template.field.historyFile")}</span>
                <span className="field-row__control">
                  <TextInput onChange={(event) => setHistoryPath(event.target.value)} value={historyPath} />
                </span>
              </label>
            </div>
            <div className="page__actions page__actions--left">
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
            </div>
          </section>
        </section>
      </div>

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
