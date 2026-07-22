import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { chatThemeQueryKey, getChatThemeManifest } from "../../../entities/chat/repository";
import { configQueryKey } from "../../../entities/config/repository";
import type { AppConfig } from "../../../entities/config/types";
import { useI18n } from "../../../shared/i18n";
import {
  chatThemeDisplayName,
  type ChatThemeManifest,
  type ChatThemeSummary,
  type ChatThemeTokens,
} from "../../../shared/theme/chatTheme";
import { useToast } from "../../../shared/ui";
import { useOptionalChatTheme } from "./ChatThemeProvider";

export type EditableThemeBlock = "dialog" | "input" | "name" | "options";

const EMPTY_THEMES: ChatThemeSummary[] = [];
const themeIdPattern = /^[a-z0-9][a-z0-9_-]{0,63}$/;

function cloneManifest(manifest: ChatThemeManifest): ChatThemeManifest {
  return JSON.parse(JSON.stringify(manifest)) as ChatThemeManifest;
}

function customThemeId(baseId: string, ids: Set<string>) {
  const base = `${baseId.replace(/-custom(?:-\d+)?$/, "")}-custom`;
  if (!ids.has(base)) {
    return base;
  }
  let suffix = 2;
  while (ids.has(`${base}-${suffix}`)) {
    suffix += 1;
  }
  return `${base}-${suffix}`;
}

export function useChatThemeCustomizer() {
  const queryClient = useQueryClient();
  const { language, t } = useI18n();
  const { showToast } = useToast();
  const theme = useOptionalChatTheme();
  const [sourceId, setSourceIdState] = useState("");
  const [assetThemeId, setAssetThemeId] = useState("");
  const [draft, setDraft] = useState<ChatThemeManifest | null>(null);
  const [original, setOriginal] = useState<ChatThemeManifest | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const loadRequestId = useRef(0);

  const themes = theme?.themes ?? EMPTY_THEMES;
  const source = themes.find((item) => item.id === sourceId);
  const isNewTheme = source?.source === "builtin";
  const sourceReady = Boolean(sourceId && assetThemeId === sourceId && draft && original && !loading);
  const dirty = Boolean(sourceReady && draft && original && JSON.stringify(draft) !== JSON.stringify(original));
  const idError = draft && !themeIdPattern.test(draft.id) ? t("chat.theme.customizer.idError") : "";
  const nameError =
    draft && !Object.values(draft.name).some((value) => value.trim()) ? t("chat.theme.customizer.nameError") : "";
  const duplicateId = Boolean(isNewTheme && draft && themes.some((item) => item.id === draft.id));
  const invalid = Boolean(idError || nameError || duplicateId);
  const themeCatalogKey = themes.map((item) => `${item.id}:${item.source}:${JSON.stringify(item.name)}`).join("|");

  const loadTheme = useCallback(
    async (id: string, requestId: number) => {
      if (!id || requestId !== loadRequestId.current) {
        return;
      }
      setLoading(true);
      setLoadError("");
      setAssetThemeId("");
      setDraft(null);
      setOriginal(null);
      try {
        const manifest = await getChatThemeManifest(id);
        if (requestId !== loadRequestId.current) {
          return;
        }
        const summary = themes.find((item) => item.id === id);
        const next = cloneManifest(manifest);
        if (summary?.source === "builtin") {
          const ids = new Set(themes.map((item) => item.id));
          next.id = customThemeId(manifest.id, ids);
          next.name = {
            ...next.name,
            [language]: t("chat.theme.customizer.customName", {
              name: chatThemeDisplayName(summary, language),
            }),
          };
          next.author = "";
          next.version = "1.0.0";
          delete next.preview;
          delete next.description;
        }
        setAssetThemeId(id);
        setDraft(next);
        setOriginal(cloneManifest(next));
      } catch (error) {
        if (requestId === loadRequestId.current) {
          setLoadError(error instanceof Error ? error.message : t("chat.theme.customizer.loadError"));
        }
      } finally {
        if (requestId === loadRequestId.current) {
          setLoading(false);
        }
      }
    },
    // The key keeps equal catalog refetches from resetting unsaved edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [language, t, themeCatalogKey],
  );

  const selectSourceId = useCallback((id: string) => {
    loadRequestId.current += 1;
    setSourceIdState(id);
    setAssetThemeId("");
    setDraft(null);
    setOriginal(null);
    setLoadError("");
    setLoading(Boolean(id));
  }, []);

  useEffect(() => {
    if (!theme || theme.loading || sourceId || !themes.length) {
      return;
    }
    const initial = themes.find((item) => item.id === theme.activeId)?.id ?? themes[0]?.id ?? "";
    selectSourceId(initial);
  }, [selectSourceId, sourceId, theme, themes]);

  useEffect(() => {
    if (sourceId) {
      const requestId = loadRequestId.current + 1;
      loadRequestId.current = requestId;
      void loadTheme(sourceId, requestId);
    }
  }, [loadTheme, sourceId]);

  const patchManifest = (patch: Partial<ChatThemeManifest>) => {
    setDraft((current) => (current ? { ...current, ...patch } : current));
  };

  const patchBlock = (block: EditableThemeBlock, patch: Record<string, unknown>) => {
    setDraft((current) => {
      if (!current) {
        return current;
      }
      const previous = (current.tokens[block] ?? {}) as Record<string, unknown>;
      return {
        ...current,
        tokens: {
          ...current.tokens,
          [block]: { ...previous, ...patch },
        },
      };
    });
  };

  const patchGlobal = (patch: NonNullable<ChatThemeTokens["global"]>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            tokens: { ...current.tokens, global: { ...(current.tokens.global ?? {}), ...patch } },
          }
        : current,
    );
  };

  const patchTypewriter = (patch: NonNullable<ChatThemeTokens["typewriter"]>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            tokens: { ...current.tokens, typewriter: { ...(current.tokens.typewriter ?? {}), ...patch } },
          }
        : current,
    );
  };

  const reset = () => {
    if (sourceReady && original) {
      setDraft(cloneManifest(original));
    }
  };

  const save = async () => {
    if (!theme || !draft || invalid || !sourceReady) {
      return;
    }
    setSaving(true);
    try {
      const summary = await theme.saveTheme({ baseId: assetThemeId, manifest: draft });
      await theme.switchTheme(summary.id);
      queryClient.setQueryData<AppConfig>(configQueryKey, (current) =>
        current
          ? {
              ...current,
              system_config: { ...current.system_config, chat_ui_theme_id: summary.id },
            }
          : current,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: configQueryKey }),
        queryClient.invalidateQueries({ queryKey: chatThemeQueryKey }),
      ]);
      setSourceIdState(summary.id);
      setAssetThemeId(summary.id);
      setOriginal(cloneManifest(draft));
      showToast({
        kind: "success",
        message: chatThemeDisplayName(summary, language),
        title: t("chat.theme.customizer.saved"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("chat.theme.customizer.saveError"),
        title: t("common.saveFailed"),
      });
    } finally {
      setSaving(false);
    }
  };

  return {
    assetThemeId,
    dirty,
    draft,
    duplicateId,
    idError,
    invalid,
    isNewTheme,
    loadError,
    loading,
    nameError,
    patchBlock,
    patchGlobal,
    patchManifest,
    patchTypewriter,
    reset,
    save,
    saving,
    setSourceId: selectSourceId,
    sourceId,
    sourceReady,
    themes,
  };
}
