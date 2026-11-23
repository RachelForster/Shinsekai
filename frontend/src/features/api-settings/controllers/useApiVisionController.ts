import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { fetchLlmModels } from "../../../entities/config/repository";
import { useI18n } from "../../../shared/i18n";
import type { LlmModelOption } from "../../../shared/platform/types";
import { useToast } from "../../../shared/ui";
import {
  activeMapValue,
  adapterSchema,
  catalogOptions,
  effectiveVisionApiKey,
  effectiveVisionBaseUrl,
  effectiveVisionModel,
  mergeModelOptions,
  resolveVisionProvider,
  visionModelFetchKey,
  visionProviderLlmProviders,
  visionProviderRequiresApiKey,
  withCurrentOption,
} from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function useApiVisionController(ctx: ApiSettingsPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [visionModelOptions, setVisionModelOptions] = useState<LlmModelOption[]>([]);
  const activeVisionModelFetchKey = useRef<string | null>(null);
  const lastConfigRevisionRef = useRef(ctx.configReloadRevision);

  useEffect(() => {
    if (ctx.configReloadRevision === lastConfigRevisionRef.current) {
      return;
    }
    lastConfigRevisionRef.current = ctx.configReloadRevision;
    activeVisionModelFetchKey.current = null;
    setVisionModelOptions([]);
  }, [ctx.configReloadRevision]);

  const visionModelFetchMutation = useMutation({
    mutationFn: (input: { apiKey: string; baseUrl: string; fetchKey: string; provider: string }) =>
      fetchLlmModels({ apiKey: input.apiKey, baseUrl: input.baseUrl, provider: input.provider }),
    onError(error, input) {
      if (activeVisionModelFetchKey.current !== input.fetchKey) return;
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.vision.fetchFailed"),
        title: t("api.vision.fetchTitle"),
      });
    },
    onMutate(input) {
      activeVisionModelFetchKey.current = input.fetchKey;
    },
    onSuccess(options, input) {
      if (activeVisionModelFetchKey.current !== input.fetchKey) return;
      setVisionModelOptions(options);
      if (!options.length) {
        showToast({ kind: "error", message: t("api.vision.fetchEmpty"), title: t("api.vision.fetchTitle") });
        return;
      }
      ctx.setDraft((current) => {
        if (!current || visionModelFetchKey(current) !== input.fetchKey) return current;
        const provider = resolveVisionProvider(current);
        const model = activeMapValue(current.vision_model, provider);
        return model ? current : { ...current, vision_model: { ...current.vision_model, [provider]: options[0].id } };
      });
      showToast({
        kind: "success",
        message: t("api.vision.fetchDone", { count: options.length }),
        title: t("api.vision.fetchTitle"),
      });
    },
  });

  const activeApiKey = effectiveVisionApiKey(ctx.draft);
  const activeBaseUrl = effectiveVisionBaseUrl(ctx.draft);
  const resolvedVisionProvider = resolveVisionProvider(ctx.draft);
  const activeModel = effectiveVisionModel(ctx.draft);
  const availableModelOptions = useMemo(
    () => mergeModelOptions(visionModelOptions, activeModel ? [{ id: activeModel, tags: ["vision"] }] : []),
    [activeModel, visionModelOptions],
  );
  const extraSchema = adapterSchema(ctx.adapterCatalog?.vision, resolvedVisionProvider);

  const providerOptions = useMemo(
    () =>
      withCurrentOption(
        catalogOptions(
          ctx.adapterCatalog?.vision,
          [
            { label: t("api.vision.auto"), value: "auto" },
            { label: "DeepSeek Vision", value: "deepseek" },
            { label: "OpenAI Vision", value: "chatgpt" },
            { label: "Gemini Vision", value: "gemini" },
            { label: "Claude Vision", value: "claude" },
            { labelKey: "ops.api.vision.doubao", value: "doubao" },
            { labelKey: "ops.api.vision.qwen", value: "qwen" },
            { labelKey: "ops.api.vision.ollamaLocal", value: "ollama" },
            { label: "Moondream", value: "moondream" },
          ],
          t,
        ).map((option) => (option.value === "auto" ? { ...option, label: t("api.vision.auto") } : option)),
        ctx.draft.vision_provider,
      ),
    [ctx.adapterCatalog?.vision, ctx.draft.vision_provider, t],
  );

  const updateVisionProvider = useCallback(
    (provider: string) => {
      activeVisionModelFetchKey.current = null;
      setVisionModelOptions([]);
      ctx.setDraft((current) =>
        current
          ? {
              ...current,
              vision_model:
                provider === "auto"
                  ? current.vision_model
                  : {
                      ...current.vision_model,
                      [provider]: current.vision_model?.[provider] ?? effectiveVisionModel(current, provider),
                    },
              vision_provider: provider,
            }
          : current,
      );
    },
    [ctx.setDraft],
  );

  const updateVisionModel = useCallback(
    (value: string) => {
      ctx.setDraft((current) =>
        current
          ? {
              ...current,
              vision_model: { ...current.vision_model, [resolvedVisionProvider]: value },
            }
          : current,
      );
    },
    [ctx.setDraft, resolvedVisionProvider],
  );

  const updateVisionSharedCredential = useCallback(
    (key: "llm_api_key" | "llm_base_urls", value: string) => {
      const provider = visionProviderLlmProviders[resolvedVisionProvider];
      if (!provider) return;
      activeVisionModelFetchKey.current = null;
      setVisionModelOptions([]);
      if (provider === ctx.draft.llm_provider) {
        ctx.invalidateLlmCredentials();
      }
      ctx.setDraft((current) =>
        current
          ? {
              ...current,
              [key]: { ...current[key], [provider]: value },
              ...(key === "llm_base_urls" && provider === current.llm_provider ? { llm_base_url: value } : {}),
            }
          : current,
      );
    },
    [ctx.draft.llm_provider, ctx.invalidateLlmCredentials, ctx.setDraft, resolvedVisionProvider],
  );

  const handleFetchModels = useCallback(() => {
    if (!activeBaseUrl.trim() || (visionProviderRequiresApiKey(resolvedVisionProvider) && !activeApiKey.trim())) {
      showToast({ kind: "error", message: t("api.vision.fetchMissing"), title: t("api.vision.fetchTitle") });
      return;
    }
    visionModelFetchMutation.mutate({
      apiKey: activeApiKey || "ollama",
      baseUrl: activeBaseUrl,
      fetchKey: visionModelFetchKey(ctx.draft),
      provider: resolvedVisionProvider,
    });
  }, [activeApiKey, activeBaseUrl, ctx.draft, resolvedVisionProvider, showToast, t, visionModelFetchMutation]);

  return {
    activeApiKey,
    activeBaseUrl,
    activeModel,
    apiKeyRequired: visionProviderRequiresApiKey(resolvedVisionProvider),
    availableModelOptions,
    extraSchema,
    fetchModelsPending: visionModelFetchMutation.isPending,
    handleFetchModels,
    providerOptions,
    resolvedVisionProvider,
    sharedLlmProvider: visionProviderLlmProviders[resolvedVisionProvider],
    updateVisionModel,
    updateVisionProvider,
    updateVisionSharedCredential,
  };
}
