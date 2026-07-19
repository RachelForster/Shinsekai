// UI 主题热切换 Provider（chat stage + logs）。
//
// 负责：拉取主题列表 + 当前 active → 解析为 CSS 变量/字体/打字机 → 提供给主题化页面；
// 切换时**无重载**应用并持久化。M0 仅搭好 context/状态机与解析调用，真实热切换副作用（注入
// @font-face、写 documentElement 变量、文件 watch）在 M5 补全。

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  deleteChatTheme,
  exportChatTheme,
  getChatTheme,
  getActiveChatThemeId,
  getChatThemeManifest,
  listChatThemes,
  saveChatTheme,
  setActiveChatTheme,
  uploadChatTheme,
} from "../../../entities/chat/repository";
import { getPlatform } from "../../../shared/platform/platform";
import { parseChatChromeTheme } from "../../../shared/theme/chatChromeTheme";
import type { ChatThemePayload } from "../../../shared/theme/chatChromeTheme";
import { DEFAULT_CHAT_THEME_ID, DEFAULT_TYPEWRITER_CPS, resolveChatTheme } from "../../../shared/theme/chatTheme";
import type {
  ChatStageStyle,
  ChatThemeManifest,
  ChatThemeSummary,
  ResolvedChatTheme,
  SaveChatThemeInput,
} from "../../../shared/theme/chatTheme";

export interface ChatThemeContextValue {
  /** 可选主题列表（含内置 + 用户 mod）。 */
  themes: ChatThemeSummary[];
  /** 当前激活的主题 id。 */
  activeId: string | null;
  /** 解析后的样式 / 字体 / 打字机参数，直接喂给 chat stage。 */
  resolved: ResolvedChatTheme | null;
  /** 仅 style 部分的便捷别名（写到 stage 根元素 style）。 */
  style: ChatStageStyle;
  loading: boolean;
  /** 热切换到指定主题（无重载）。 */
  switchTheme: (id: string) => Promise<void>;
  /** 重新扫描主题目录（拾取新装的 mod）。 */
  refresh: () => Promise<void>;
  /** 上传 .zip 安装一个主题，安装后刷新列表并返回其概要。 */
  uploadTheme: (file: File) => Promise<ChatThemeSummary>;
  /** 创建或保存用户主题，并刷新主题列表。 */
  saveTheme: (input: SaveChatThemeInput) => Promise<ChatThemeSummary>;
  /** 删除一个用户主题，删除后刷新列表。 */
  removeTheme: (id: string) => Promise<void>;
  /** 导出一个可重新导入的主题 ZIP。 */
  exportTheme: (id: string) => Promise<string>;
}

const ChatThemeContext = createContext<ChatThemeContextValue | null>(null);

function assetUrl(rel: string): string {
  return getPlatform().files.fileUrl(rel);
}

export function chatThemeAssetUrl(themeId: string, rel: string): string {
  const normalizedThemeId = themeId.trim();
  const normalizedRel = rel.replace(/^\.?\//, "").replace(/^\/+/, "");
  return assetUrl(`data/chat_ui_themes/${normalizedThemeId}/${normalizedRel}`);
}

export function ChatThemeProvider({ children }: { children: ReactNode }) {
  const [themes, setThemes] = useState<ChatThemeSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ChatThemeManifest | null>(null);
  const [legacyTheme, setLegacyTheme] = useState<ChatThemePayload | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const list = await listChatThemes();
    setThemes(list);
  }, []);

  const applyManifest = useCallback((next: ChatThemeManifest | null) => {
    setManifest(next);
  }, []);

  const switchTheme = useCallback(
    async (id: string) => {
      const next = await getChatThemeManifest(id);
      await setActiveChatTheme(id);
      setActiveId(id);
      applyManifest(next);
    },
    [applyManifest],
  );

  const uploadTheme = useCallback(
    async (file: File) => {
      const summary = await uploadChatTheme(file);
      await refresh();
      return summary;
    },
    [refresh],
  );

  const saveTheme = useCallback(
    async (input: SaveChatThemeInput) => {
      const summary = await saveChatTheme(input);
      await refresh();
      return summary;
    },
    [refresh],
  );

  const removeTheme = useCallback(
    async (id: string) => {
      await deleteChatTheme(id);
      if (activeId === id) {
        setActiveId(null);
        applyManifest(null);
      }
      await refresh();
    },
    [activeId, applyManifest, refresh],
  );

  const exportTheme = useCallback((id: string) => exportChatTheme(id), []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [persistedId, legacyPayload] = await Promise.all([
          getActiveChatThemeId().catch(() => ""),
          getChatTheme().catch(() => null),
          refresh().then(
            () => undefined,
            () => undefined,
          ),
        ]);
        if (!mounted) {
          return;
        }
        const themeId = persistedId || DEFAULT_CHAT_THEME_ID;
        const nextManifest = await getChatThemeManifest(themeId).catch(() =>
          themeId === DEFAULT_CHAT_THEME_ID ? null : getChatThemeManifest(DEFAULT_CHAT_THEME_ID).catch(() => null),
        );
        if (!mounted) {
          return;
        }
        setLegacyTheme(legacyPayload);
        setActiveId(nextManifest?.id ?? null);
        applyManifest(nextManifest);
      } catch {
        // 占位：主题不可用时回退到 chat-stage.css 默认变量。
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, [applyManifest, refresh]);

  const resolved = useMemo(() => {
    const fallbackStyle = parseChatChromeTheme(legacyTheme);
    if (!manifest) {
      return {
        fontFaces: "",
        style: fallbackStyle,
        typewriter: { cps: DEFAULT_TYPEWRITER_CPS },
      } satisfies ResolvedChatTheme;
    }
    const next = resolveChatTheme(manifest, (rel) => chatThemeAssetUrl(manifest.id, rel));
    return {
      ...next,
      style: { ...fallbackStyle, ...next.style },
    } satisfies ResolvedChatTheme;
  }, [legacyTheme, manifest]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const root = document.documentElement;
    const entries = Object.entries(resolved.style).filter(
      (entry): entry is [`--${string}`, string] => entry[0].startsWith("--") && typeof entry[1] === "string",
    );
    for (const [name, value] of entries) {
      root.style.setProperty(name, value);
    }
    return () => {
      for (const [name] of entries) {
        root.style.removeProperty(name);
      }
    };
  }, [resolved]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const styleId = "shinsekai-chat-theme-fonts";
    let node = document.getElementById(styleId) as HTMLStyleElement | null;
    if (!resolved.fontFaces.trim()) {
      node?.remove();
      return;
    }
    if (!node) {
      node = document.createElement("style");
      node.id = styleId;
      document.head.appendChild(node);
    }
    node.textContent = resolved.fontFaces;
    return () => {
      node?.remove();
    };
  }, [resolved]);

  const value = useMemo<ChatThemeContextValue>(
    () => ({
      themes,
      activeId,
      resolved,
      style: resolved.style,
      loading,
      switchTheme,
      refresh,
      uploadTheme,
      saveTheme,
      removeTheme,
      exportTheme,
    }),
    [themes, activeId, resolved, loading, switchTheme, refresh, uploadTheme, saveTheme, removeTheme, exportTheme],
  );

  return <ChatThemeContext.Provider value={value}>{children}</ChatThemeContext.Provider>;
}

export function useOptionalChatTheme(): ChatThemeContextValue | null {
  return useContext(ChatThemeContext);
}

export function useChatTheme(): ChatThemeContextValue {
  const ctx = useOptionalChatTheme();
  if (!ctx) {
    throw new Error("useChatTheme must be used within a ChatThemeProvider");
  }
  return ctx;
}
