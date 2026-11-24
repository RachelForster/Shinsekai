import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { fetchLlmModels, testLlmConnection } from "../../../entities/config/repository";
import type { ApiConfig } from "../../../entities/config/types";
import { formatLlmProviderLabel, useI18n } from "../../../shared/i18n";
import type { LlmModelOption } from "../../../shared/platform/types";
import { useToast } from "../../../shared/ui";
import {
  activeMapValue,
  adapterSchema,
  catalogOptions,
  llmDefaultBaseUrls,
  llmModelFetchKey,
  llmProviderOptions,
  mergeModelOptions,
  thinkingUnsupported,
  withCurrentOption,
} from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function useApiLlmController(ctx: ApiSettingsPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [modelOptions, setModelOptions] = useState<LlmModelOption[]>([]);
  const [llmConnectionDialog, setLlmConnectionDialog] = useState<{ kind: "error" | "success"; message: string } | null>(
    null,
  );
  const [llmConnectionOk, setLlmConnectionOk] = useState(false);
  const activeModelFetchKey = useRef<string | null>(null);
  const lastConfigRevisionRef = useRef(ctx.configReloadRevision);
  const lastCredentialRevisionRef = useRef(ctx.llmCredentialRevision);

  useEffect(() => {
    const configChanged = ctx.configReloadRevision !== lastConfigRevisionRef.current;
    const credentialChanged = ctx.llmCredentialRevision !== lastCredentialRevisionRef.current;
    lastConfigRevisionRef.current = ctx.configReloadRevision;
    lastCredentialRevisionRef.current = ctx.llmCredentialRevision;
    if (!configChanged && !credentialChanged) {
      return;
    }
    activeModelFetchKey.current = null;
    setModelOptions([]);
    if (credentialChanged) {
      setLlmConnectionOk(false);
    }
  }, [ctx.configReloadRevision, ctx.llmCredentialRevision]);

  const modelFetchMutation = useMutation({
    mutationFn: (input: { apiKey: string; baseUrl: string; fetchKey: string; provider: string }) =>
      fetchLlmModels({
        apiKey: input.apiKey,
        baseUrl: input.baseUrl,
        provider: input.provider,
      }),
    onError(error, input) {
      if (activeModelFetchKey.current !== input.fetchKey) {
        return;
      }
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.llm.fetchFailed"),
        title: t("api.llm.fetchTitle"),
      });
    },
    onMutate(input) {
      activeModelFetchKey.current = input.fetchKey;
    },
    onSuccess(options, input) {
      if (activeModelFetchKey.current !== input.fetchKey) {
        return;
      }
      setModelOptions(options);
      if (!options.length) {
        showToast({ kind: "error", message: t("api.llm.fetchEmpty"), title: t("api.llm.fetchTitle") });
        return;
      }
      ctx.setDraft((current) => {
        if (!current) {
          return current;
        }
        if (llmModelFetchKey(current) !== input.fetchKey) {
          return current;
        }
        const model = activeMapValue(current.llm_model, current.llm_provider);
        if (model) {
          return current;
        }
        return {
          ...current,
          llm_model: { ...current.llm_model, [current.llm_provider]: options[0].id },
        };
      });
      showToast({
        kind: "success",
        message: t("api.llm.fetchDone", { count: options.length }),
        title: t("api.llm.fetchTitle"),
      });
    },
  });

  const llmConnectionTestMutation = useMutation({
    mutationFn: (input: { apiKey: string; baseUrl: string; model: string; provider: string }) =>
      testLlmConnection(input),
    onError(error) {
      setLlmConnectionOk(false);
      setLlmConnectionDialog({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.llm.testFailed"),
      });
    },
    onSuccess(result) {
      setLlmConnectionOk(true);
      setLlmConnectionDialog({
        kind: "success",
        message: result.message || t("api.llm.testDone"),
      });
    },
  });

  const activeModel = activeMapValue(ctx.draft.llm_model, ctx.draft.llm_provider);
  const activeApiKey = activeMapValue(ctx.draft.llm_api_key, ctx.draft.llm_provider);
  const availableModelOptions = useMemo(
    () => mergeModelOptions(modelOptions, activeModel ? [{ id: activeModel, tags: [] }] : []),
    [activeModel, modelOptions],
  );
  const selectedOption = availableModelOptions.find((option) => option.id === activeModel);

  const updateDraftAndResetModelFetch = useCallback(
    (patch: Partial<ApiConfig>) => {
      if (Object.prototype.hasOwnProperty.call(patch, "llm_base_url")) {
        activeModelFetchKey.current = null;
        setModelOptions([]);
        setLlmConnectionOk(false);
        const baseUrl = String(patch.llm_base_url ?? "");
        ctx.setDraft((current) =>
          current
            ? {
                ...current,
                ...patch,
                llm_base_urls: { ...current.llm_base_urls, [current.llm_provider]: baseUrl },
              }
            : current,
        );
        return;
      }
      ctx.updateDraft(patch);
    },
    [ctx.setDraft, ctx.updateDraft],
  );

  const updateProvider = useCallback(
    (provider: string) => {
      activeModelFetchKey.current = null;
      setModelOptions([]);
      setLlmConnectionOk(false);
      ctx.setDraft((current) => {
        if (!current) return current;
        const baseUrl = activeMapValue(current.llm_base_urls, provider) || llmDefaultBaseUrls[provider] || "";
        return {
          ...current,
          llm_base_url: baseUrl,
          llm_base_urls: { ...current.llm_base_urls, [provider]: baseUrl },
          llm_provider: provider,
        };
      });
    },
    [ctx.setDraft],
  );

  const updateProviderMap = useCallback(
    (key: "llm_api_key" | "llm_model", value: string) => {
      if (key === "llm_api_key") {
        activeModelFetchKey.current = null;
        setModelOptions([]);
      }
      setLlmConnectionOk(false);
      ctx.setDraft((current) => {
        if (!current) return current;
        const nextExtra =
          key === "llm_model" && thinkingUnsupported(value)
            ? {
                llm_extra_configs: {
                  ...current.llm_extra_configs,
                  [current.llm_provider]: {
                    ...(current.llm_extra_configs?.[current.llm_provider] ?? {}),
                    thinking_enabled: false,
                  },
                },
              }
            : {};
        return {
          ...current,
          [key]: {
            ...current[key],
            [current.llm_provider]: value,
          },
          ...nextExtra,
        };
      });
    },
    [ctx.setDraft],
  );

  const handleFetchModels = useCallback(() => {
    if (!ctx.draft.llm_base_url.trim() || !activeApiKey.trim()) {
      showToast({ kind: "error", message: t("api.llm.fetchMissing"), title: t("api.llm.fetchTitle") });
      return;
    }
    modelFetchMutation.mutate({
      apiKey: activeApiKey,
      baseUrl: ctx.draft.llm_base_url,
      fetchKey: llmModelFetchKey(ctx.draft),
      provider: ctx.draft.llm_provider,
    });
  }, [activeApiKey, ctx.draft, modelFetchMutation, showToast, t]);

  const handleTestLlmConnection = useCallback(() => {
    if (!ctx.draft.llm_base_url.trim() || !activeApiKey.trim()) {
      setLlmConnectionOk(false);
      setLlmConnectionDialog({ kind: "error", message: t("api.llm.fetchMissing") });
      return;
    }
    if (!activeModel.trim()) {
      setLlmConnectionOk(false);
      setLlmConnectionDialog({ kind: "error", message: t("api.llm.testMissingModel") });
      return;
    }
    llmConnectionTestMutation.mutate({
      apiKey: activeApiKey,
      baseUrl: ctx.draft.llm_base_url,
      model: activeModel,
      provider: ctx.draft.llm_provider,
    });
  }, [activeApiKey, activeModel, ctx.draft.llm_base_url, ctx.draft.llm_provider, llmConnectionTestMutation, t]);

  const llmProviderSelectOptions = useMemo(
    () =>
      withCurrentOption(
        catalogOptions(ctx.adapterCatalog?.llm, llmProviderOptions, t).map((option) => ({
          ...option,
          label: formatLlmProviderLabel(option.value, t) || option.label,
        })),
        ctx.draft.llm_provider,
      ),
    [ctx.adapterCatalog?.llm, ctx.draft.llm_provider, t],
  );
  const llmExtraSchema = adapterSchema(ctx.adapterCatalog?.llm, ctx.draft.llm_provider);

  return {
    activeApiKey,
    activeModel,
    availableModelOptions,
    closeConnectionDialog: () => setLlmConnectionDialog(null),
    connectionOk: llmConnectionOk,
    connectionTestPending: llmConnectionTestMutation.isPending,
    fetchModelsPending: modelFetchMutation.isPending,
    handleFetchModels,
    handleTestLlmConnection,
    llmConnectionDialog,
    llmExtraSchema,
    llmProviderSelectOptions,
    modelCandidateListId: "llm-model-candidates",
    modelUnsupportedThinking: thinkingUnsupported(activeModel),
    selectedOption,
    updateDraftAndResetModelFetch,
    updateProvider,
    updateProviderMap,
  };
}
