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

interface DraftHistory {
  future: ChatThemeManifest[];
  past: ChatThemeManifest[];
  present: ChatThemeManifest | null;
}

const EMPTY_THEMES: ChatThemeSummary[] = [];
const themeIdPattern = /^[a-z0-9][a-z0-9_-]{0,63}$/;

function cloneManifest(manifest: ChatThemeManifest): ChatThemeManifest {
  return JSON.parse(JSON.stringify(manifest)) as ChatThemeManifest;
}

function valueAtPath(source: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, segment) => {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    return (current as Record<string, unknown>)[segment];
  }, source);
}

export function patchChatThemeTokenPath(tokens: ChatThemeTokens, path: string, value: unknown): ChatThemeTokens {
  const segments = path.split(".").filter(Boolean);
  if (!segments.length) {
    return tokens;
  }
  const root = cloneManifest({ schema: 1, id: "draft", name: { en: "Draft" }, tokens }).tokens as Record<
    string,
    unknown
  >;
  let cursor = root;
  for (const segment of segments.slice(0, -1)) {
    const child = cursor[segment];
    if (!child || typeof child !== "object" || Array.isArray(child)) {
      cursor[segment] = {};
    }
    cursor = cursor[segment] as Record<string, unknown>;
  }
  const finalSegment = segments[segments.length - 1];
  if (value === undefined) {
    delete cursor[finalSegment];
  } else {
    cursor[finalSegment] = value;
  }

  const prune = (target: Record<string, unknown>) => {
    for (const [key, child] of Object.entries(target)) {
      if (child && typeof child === "object" && !Array.isArray(child)) {
        prune(child as Record<string, unknown>);
        if (!Object.keys(child as Record<string, unknown>).length) {
          delete target[key];
        }
      }
    }
  };
  prune(root);
  return root as ChatThemeTokens;
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
  const [draftHistory, setDraftHistory] = useState<DraftHistory>({ future: [], past: [], present: null });
  const [original, setOriginal] = useState<ChatThemeManifest | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const loadRequestId = useRef(0);

  const themes = theme?.themes ?? EMPTY_THEMES;
  const draft = draftHistory.present;
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

  const replaceDraft = useCallback((present: ChatThemeManifest | null) => {
    setDraftHistory({ future: [], past: [], present });
  }, []);

  const updateDraft = useCallback((updater: (current: ChatThemeManifest) => ChatThemeManifest) => {
    setDraftHistory((current) => {
      if (!current.present) {
        return current;
      }
      const next = updater(current.present);
      if (JSON.stringify(next) === JSON.stringify(current.present)) {
        return current;
      }
      return {
        future: [],
        past: [...current.past, cloneManifest(current.present)].slice(-50),
        present: next,
      };
    });
  }, []);

  const loadTheme = useCallback(
    async (id: string, requestId: number) => {
      if (!id || requestId !== loadRequestId.current) {
        return;
      }
      setLoading(true);
      setLoadError("");
      setAssetThemeId("");
      replaceDraft(null);
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
        replaceDraft(next);
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
    [language, replaceDraft, t, themeCatalogKey],
  );

  const selectSourceId = useCallback(
    (id: string) => {
      loadRequestId.current += 1;
      setSourceIdState(id);
      setAssetThemeId("");
      replaceDraft(null);
      setOriginal(null);
      setLoadError("");
      setLoading(Boolean(id));
    },
    [replaceDraft],
  );

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
    updateDraft((current) => ({ ...current, ...patch }));
  };

  const patchBlock = (block: EditableThemeBlock, patch: Record<string, unknown>) => {
    updateDraft((current) => {
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
    updateDraft((current) => ({
      ...current,
      tokens: { ...current.tokens, global: { ...(current.tokens.global ?? {}), ...patch } },
    }));
  };

  const patchTypewriter = (patch: NonNullable<ChatThemeTokens["typewriter"]>) => {
    updateDraft((current) => ({
      ...current,
      tokens: { ...current.tokens, typewriter: { ...(current.tokens.typewriter ?? {}), ...patch } },
    }));
  };

  const patchToken = (path: string, value: unknown) => {
    updateDraft((current) => ({ ...current, tokens: patchChatThemeTokenPath(current.tokens, path, value) }));
  };

  const resetSection = (path: string) => {
    if (!original) {
      return;
    }
    const value = valueAtPath(original.tokens, path);
    patchToken(path, value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
  };

  const reset = () => {
    if (sourceReady && original) {
      updateDraft(() => cloneManifest(original));
    }
  };

  const undo = () => {
    setDraftHistory((current) => {
      const previous = current.past.at(-1);
      if (!previous || !current.present) {
        return current;
      }
      return {
        future: [cloneManifest(current.present), ...current.future].slice(0, 50),
        past: current.past.slice(0, -1),
        present: cloneManifest(previous),
      };
    });
  };

  const redo = () => {
    setDraftHistory((current) => {
      const next = current.future[0];
      if (!next || !current.present) {
        return current;
      }
      return {
        future: current.future.slice(1),
        past: [...current.past, cloneManifest(current.present)].slice(-50),
        present: cloneManifest(next),
      };
    });
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
      replaceDraft(cloneManifest(draft));
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
    patchToken,
    patchTypewriter,
    canRedo: draftHistory.future.length > 0,
    canUndo: draftHistory.past.length > 0,
    redo,
    reset,
    resetSection,
    save,
    saving,
    setSourceId: selectSourceId,
    sourceId,
    sourceReady,
    themes,
    undo,
  };
}
