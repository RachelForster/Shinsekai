import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RotateCcw, Save } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { backgroundsQueryKey, listBackgrounds } from "../../../entities/background/repository";
import { charactersQueryKey, listCharacters } from "../../../entities/character/repository";
import { launchChat, resumeLastChat } from "../../../entities/chat/repository";
import {
  listTemplates,
  saveTemplate,
  saveTemplateSession,
  templatesQueryKey,
} from "../../../entities/template/repository";
import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import type { ChatLaunchPayload, TemplateLaunchSession, TemplateSummary } from "../../../shared/platform/types";
import {
  AsyncButton,
  EmptyState,
  QueryErrorState,
  Select,
  Switch,
  TextArea,
  TextInput,
  useToast,
} from "../../../shared/ui";
import { FieldBlock, OnboardingPanelLayout, OnboardingTaskPanel } from "../OnboardingPanelLayout";
import type { OnboardingCopy } from "../onboardingCopy";

interface ChatSetupPanelProps {
  copy: OnboardingCopy;
}

function quickTemplate(
  name: string,
  characterNames: string[],
  backgroundName: string,
  scenario: string,
): TemplateSummary {
  const now = new Date().toISOString();
  return {
    content: scenario,
    id: `onboarding-${Date.now()}`,
    name,
    path: "",
    scenario,
    system: "You are a vivid roleplay partner. Keep responses concise, emotive, and grounded in the selected scene.",
    updatedAt: now,
  };
}

function launchSession(
  template: TemplateSummary,
  characterNames: string[],
  backgroundName: string,
  toggles: {
    useCg: boolean;
    useChoice: boolean;
    useCot: boolean;
    useEffect: boolean;
    useNarration: boolean;
    useStat: boolean;
    useTranslation: boolean;
  },
): TemplateLaunchSession {
  return {
    background: backgroundName,
    filenameStub: template.name,
    historyPath: "",
    initSpritePath: "",
    maxDialogItems: 0,
    maxSpeechChars: 0,
    roomId: "",
    scenario: template.scenario ?? "",
    selectedCharacters: characterNames,
    system: template.system ?? "",
    templateFileDropdown: template.id,
    useCg: toggles.useCg,
    useChoice: toggles.useChoice,
    useCot: toggles.useCot,
    useEffect: toggles.useEffect,
    useNarration: toggles.useNarration,
    useStat: toggles.useStat,
    useTranslation: toggles.useTranslation,
    voiceLanguage: "ja",
  };
}

export function ChatSetupPanel({ copy }: ChatSetupPanelProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const templatesQuery = useQuery({ queryFn: listTemplates, queryKey: templatesQueryKey });
  const characters = charactersQuery.data ?? [];
  const backgrounds = backgroundsQuery.data ?? [];
  const templates = templatesQuery.data ?? [];
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>([]);
  const [backgroundName, setBackgroundName] = useState(TRANSPARENT_BACKGROUND_NAME);
  const [templateId, setTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("First Chat");
  const [scenario, setScenario] = useState(
    "A calm first meeting where everyone introduces themselves and starts a friendly conversation.",
  );
  const [useCg, setUseCg] = useState(false);
  const [useChoice, setUseChoice] = useState(true);
  const [useCot, setUseCot] = useState(false);
  const [useSceneEffect, setUseSceneEffect] = useState(true);
  const [useNarration, setUseNarration] = useState(true);
  const [useStat, setUseStat] = useState(true);
  const [useTranslation, setUseTranslation] = useState(true);

  const backgroundOptions = useMemo(() => {
    const names = backgrounds.map((background) => background.name);
    return names.includes(TRANSPARENT_BACKGROUND_NAME) ? names : [...names, TRANSPARENT_BACKGROUND_NAME];
  }, [backgrounds]);
  const selectedTemplate = templates.find((template) => template.id === templateId) ?? null;
  const isLoading = charactersQuery.isLoading || backgroundsQuery.isLoading || templatesQuery.isLoading;
  const failedQuery = [charactersQuery, backgroundsQuery, templatesQuery].find((query) => query.isError);

  useEffect(() => {
    if (!selectedCharacters.length && characters[0]) {
      setSelectedCharacters([characters[0].name]);
    }
    if (!backgroundName || !backgroundOptions.includes(backgroundName)) {
      setBackgroundName(backgroundOptions[0] ?? TRANSPARENT_BACKGROUND_NAME);
    }
    if (!templateId && templates[0]) {
      setTemplateId(templates[0].id);
      setTemplateName(templates[0].name);
    }
  }, [backgroundName, backgroundOptions, characters, selectedCharacters.length, templateId, templates]);

  const saveTemplateMutation = useMutation({
    mutationFn: () =>
      saveTemplate(quickTemplate(templateName.trim() || "First Chat", selectedCharacters, backgroundName, scenario)),
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(template) {
      queryClient.setQueryData(templatesQueryKey, (current: TemplateSummary[] | undefined) => [
        ...(current ?? []),
        template,
      ]);
      setTemplateId(template.id);
      setTemplateName(template.name);
      showToast({ kind: "success", title: copy.chat.templateCreated });
    },
  });

  const launchMutation = useMutation({
    mutationFn: async (payload: ChatLaunchPayload) => {
      const template = selectedTemplate;
      if (template) {
        await saveTemplateSession(
          launchSession(template, selectedCharacters, backgroundName, {
            useCg,
            useChoice,
            useCot,
            useEffect: useSceneEffect,
            useNarration,
            useStat,
            useTranslation,
          }),
        );
      }
      return launchChat(payload);
    },
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(snapshot) {
      showToast({ kind: "success", message: snapshot.dialogText, title: copy.actions.launch });
      navigate("/chat");
    },
  });

  const resumeMutation = useMutation({
    mutationFn: resumeLastChat,
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(snapshot) {
      showToast({ kind: "success", message: snapshot.dialogText, title: copy.actions.resume });
      navigate("/chat");
    },
  });

  if (isLoading) {
    return <EmptyState title={copy.common.loading} />;
  }

  if (failedQuery?.isError) {
    return (
      <QueryErrorState
        error={failedQuery.error}
        onRetry={() => {
          void charactersQuery.refetch();
          void backgroundsQuery.refetch();
          void templatesQuery.refetch();
        }}
        retryLabel={copy.actions.retry}
        title={copy.toastFailed}
      />
    );
  }

  const canCreateTemplate = Boolean(selectedCharacters.length && backgroundName && scenario.trim());
  const canLaunch = Boolean(selectedCharacters.length && backgroundName && selectedTemplate);

  return (
    <OnboardingPanelLayout
      copy={copy}
      description={copy.chat.description}
      title={copy.chat.title}
      actions={
        <>
          <AsyncButton
            disabled={!canCreateTemplate}
            icon={<Save aria-hidden size={16} />}
            loading={saveTemplateMutation.isPending}
            onClick={() => saveTemplateMutation.mutate()}
          >
            {copy.actions.save}
          </AsyncButton>
          <AsyncButton
            disabled={!canLaunch}
            icon={<Play aria-hidden size={16} />}
            loading={launchMutation.isPending}
            onClick={() => {
              if (!selectedTemplate) {
                return;
              }
              launchMutation.mutate({
                backgroundName,
                characters: selectedCharacters,
                historyPath: "",
                resetHistory: false,
                scenario,
                system: selectedTemplate.system ?? "",
                templateId: selectedTemplate.id,
                templateName: selectedTemplate.name,
                useCg,
              });
            }}
            variant="primary"
          >
            {copy.actions.launch}
          </AsyncButton>
          <AsyncButton
            icon={<RotateCcw aria-hidden size={16} />}
            loading={resumeMutation.isPending}
            onClick={() => resumeMutation.mutate()}
          >
            {copy.actions.resume}
          </AsyncButton>
        </>
      }
    >
      <OnboardingTaskPanel defaultOpen description={copy.chat.multiCharacterHint} title={copy.chat.character}>
        <div className="onboarding-form-grid">
          <FieldBlock
            help={!characters.length ? copy.chat.noCharacter : copy.chat.multiCharacterHint}
            label={copy.chat.character}
          >
            <Select
              disabled={!characters.length}
              multiple
              onChange={(event) =>
                setSelectedCharacters(Array.from(event.currentTarget.selectedOptions).map((option) => option.value))
              }
              value={selectedCharacters}
            >
              {characters.map((character) => (
                <option key={character.name} value={character.name}>
                  {character.name}
                </option>
              ))}
            </Select>
          </FieldBlock>
          <FieldBlock
            help={!backgroundOptions.length ? copy.chat.noBackground : undefined}
            label={copy.chat.background}
          >
            <Select onChange={(event) => setBackgroundName(event.target.value)} value={backgroundName}>
              {backgroundOptions.map((background) => (
                <option key={background} value={background}>
                  {background}
                </option>
              ))}
            </Select>
          </FieldBlock>
        </div>
      </OnboardingTaskPanel>
      <OnboardingTaskPanel defaultOpen description={copy.chat.description} title={copy.chat.scenario}>
        <div className="onboarding-form-grid">
          <FieldBlock label={copy.chat.template}>
            <Select
              disabled={!templates.length}
              onChange={(event) => {
                const next = templates.find((template) => template.id === event.target.value);
                setTemplateId(event.target.value);
                if (next) {
                  setTemplateName(next.name);
                  setScenario(next.scenario || next.content || scenario);
                }
              }}
              value={templateId}
            >
              <option value="">{templates.length ? copy.common.selectPlaceholder : copy.chat.noTemplate}</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </Select>
          </FieldBlock>
          <FieldBlock label={copy.chat.template}>
            <TextInput onChange={(event) => setTemplateName(event.target.value)} value={templateName} />
          </FieldBlock>
          <FieldBlock label={copy.chat.scenario}>
            <TextArea onChange={(event) => setScenario(event.target.value)} value={scenario} />
          </FieldBlock>
        </div>
      </OnboardingTaskPanel>
      <OnboardingTaskPanel description={copy.chat.description} title={copy.chat.togglesTitle}>
        <p className="onboarding-chat-option-help">{copy.chat.optionHelp}</p>
        <div className="onboarding-toggle-grid">
          <Switch checked={useChoice} onChange={(event) => setUseChoice(event.target.checked)}>
            {copy.chat.toggleChoice}
          </Switch>
          <Switch checked={useNarration} onChange={(event) => setUseNarration(event.target.checked)}>
            {copy.chat.toggleNarration}
          </Switch>
          <Switch checked={useSceneEffect} onChange={(event) => setUseSceneEffect(event.target.checked)}>
            {copy.chat.toggleEffect}
          </Switch>
          <Switch checked={useTranslation} onChange={(event) => setUseTranslation(event.target.checked)}>
            {copy.chat.toggleTranslation}
          </Switch>
          <Switch checked={useStat} onChange={(event) => setUseStat(event.target.checked)}>
            {copy.chat.toggleStat}
          </Switch>
          <Switch checked={useCg} onChange={(event) => setUseCg(event.target.checked)}>
            {copy.chat.toggleCg}
          </Switch>
          <Switch checked={useCot} onChange={(event) => setUseCot(event.target.checked)}>
            {copy.chat.toggleCot}
          </Switch>
        </div>
      </OnboardingTaskPanel>
    </OnboardingPanelLayout>
  );
}
