import { useEffect, useRef, useState } from "react";

import { useOptionalI18n, type FrontendLanguage } from "../i18n";
import { resolvePlatformHttpUrl } from "../platform/platform";
import type { PluginActionRunContext } from "../platform/types";
import { normalizeThemeColor } from "../theme/appTheme";
import { useOptionalQueryClient } from "./optionalQueryClient";
import { invalidatePluginRefreshTargets } from "./pluginRefresh";

interface HostThemeSnapshot {
  accent: string;
  colorScheme: "dark" | "light";
  density: "compact" | "normal";
}

export interface PluginIframeHostProps {
  className?: string;
  context?: PluginActionRunContext;
  frontendUrl: string;
  maxHeight?: number;
  minHeight?: number;
  pluginId?: string;
  slot?: string;
  surface?: "page" | "section";
  title: string;
}

function readHostTheme(element: HTMLElement | null): HostThemeSnapshot {
  const root = typeof document !== "undefined" ? document.documentElement : null;
  const computedAccent =
    root && typeof getComputedStyle === "function" ? getComputedStyle(root).getPropertyValue("--theme-accent") : "";
  const inlineAccent = root?.style.getPropertyValue("--theme-accent") ?? "";
  const accent = normalizeThemeColor(inlineAccent || computedAccent);

  const darkPreferred =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  const rawScheme =
    root && typeof getComputedStyle === "function" ? getComputedStyle(root).colorScheme.trim().toLowerCase() : "";
  const colorScheme: "dark" | "light" =
    rawScheme === "dark" || rawScheme === "light" ? rawScheme : darkPreferred ? "dark" : "light";

  const densitySource =
    element?.closest?.("[data-density]") ??
    (typeof document !== "undefined" ? document.querySelector("[data-density]") : null) ??
    root;
  const density: "compact" | "normal" =
    densitySource?.getAttribute("data-density") === "compact" ? "compact" : "normal";

  return { accent, colorScheme, density };
}

function buildIframeUrl(
  baseResolvedUrl: string,
  initial: {
    context?: PluginActionRunContext;
    language: FrontendLanguage;
    slot?: string;
    surface: "page" | "section";
    theme: HostThemeSnapshot;
  },
): { src: string; targetOrigin: string } {
  const originBase = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1";
  const parsed = new URL(baseResolvedUrl, originBase);
  parsed.searchParams.set("themeAccent", initial.theme.accent);
  parsed.searchParams.set("colorScheme", initial.theme.colorScheme);
  parsed.searchParams.set("density", initial.theme.density);
  parsed.searchParams.set("lang", initial.language);
  parsed.searchParams.set("surface", initial.surface);
  if (initial.context?.page) parsed.searchParams.set("page", initial.context.page);
  if (initial.slot) parsed.searchParams.set("slot", initial.slot);
  if (initial.context?.entityType) parsed.searchParams.set("entityType", initial.context.entityType);
  if (initial.context?.entityId) parsed.searchParams.set("entityId", initial.context.entityId);

  const isAbsolute = /^https?:\/\//i.test(baseResolvedUrl);
  const src = isAbsolute ? parsed.toString() : `${parsed.pathname}${parsed.search}${parsed.hash}`;
  return { src, targetOrigin: parsed.origin };
}

export function PluginIframeHost({
  className = "",
  context,
  frontendUrl,
  maxHeight = 960,
  minHeight = 140,
  slot,
  surface = "page",
  title,
}: PluginIframeHostProps) {
  const queryClient = useOptionalQueryClient();
  const { language } = useOptionalI18n();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [sectionHeight, setSectionHeight] = useState<number>(minHeight);
  const [themeSnapshot, setThemeSnapshot] = useState<HostThemeSnapshot>(() => readHostTheme(null));

  const baseResolvedUrl = resolvePlatformHttpUrl(frontendUrl);
  const frameSeedRef = useRef<{ key: string; src: string; targetOrigin: string } | null>(null);
  const frameKey = `${baseResolvedUrl}\0${surface}`;
  if (!frameSeedRef.current || frameSeedRef.current.key !== frameKey) {
    const built = buildIframeUrl(baseResolvedUrl, {
      context,
      language,
      slot,
      surface,
      theme: themeSnapshot,
    });
    frameSeedRef.current = { key: frameKey, ...built };
  }
  const { src, targetOrigin } = frameSeedRef.current;

  const normalizedMinHeight = Math.max(80, minHeight);
  const normalizedMaxHeight = Math.max(normalizedMinHeight, maxHeight);
  useEffect(() => {
    setSectionHeight(normalizedMinHeight);
  }, [frameKey, normalizedMinHeight]);

  const contextPayload = {
    entityId: context?.entityId ?? "",
    entityType: context?.entityType ?? "",
    extra: context?.extra ?? {},
    page: context?.page ?? "",
    slot: slot ?? "",
    surface,
  };
  const contextSignature = JSON.stringify(contextPayload);

  const pushStateToIframe = (theme: HostThemeSnapshot, nextLanguage: FrontendLanguage) => {
    const frameWindow = iframeRef.current?.contentWindow;
    if (!frameWindow || !targetOrigin || targetOrigin === "null") {
      return;
    }
    frameWindow.postMessage({ __shinsekai: "plugin-host", theme, type: "theme.change" }, targetOrigin);
    frameWindow.postMessage(
      { __shinsekai: "plugin-host", language: nextLanguage, type: "locale.change" },
      targetOrigin,
    );
    frameWindow.postMessage(
      { __shinsekai: "plugin-host", context: JSON.parse(contextSignature), type: "context.change" },
      targetOrigin,
    );
  };

  useEffect(() => {
    const syncTheme = () => {
      const next = readHostTheme(iframeRef.current);
      setThemeSnapshot((current) =>
        current.accent === next.accent && current.colorScheme === next.colorScheme && current.density === next.density
          ? current
          : next,
      );
    };
    syncTheme();

    const observer = typeof MutationObserver === "function" ? new MutationObserver(() => syncTheme()) : null;
    if (observer && typeof document !== "undefined") {
      observer.observe(document.documentElement, { attributeFilter: ["style", "data-density"], attributes: true });
      const densityNode = iframeRef.current?.closest?.("[data-density]") ?? document.querySelector("[data-density]");
      if (densityNode && densityNode !== document.documentElement) {
        observer.observe(densityNode, { attributeFilter: ["data-density"], attributes: true });
      }
    }

    const mediaQuery =
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;
    mediaQuery?.addEventListener?.("change", syncTheme);

    return () => {
      observer?.disconnect();
      mediaQuery?.removeEventListener?.("change", syncTheme);
    };
  }, []);

  useEffect(() => {
    pushStateToIframe(themeSnapshot, language);
  }, [contextSignature, language, targetOrigin, themeSnapshot]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frameWindow = iframeRef.current?.contentWindow;
      if (!frameWindow || event.source !== frameWindow) {
        return;
      }
      if (targetOrigin && targetOrigin !== "*" && event.origin !== targetOrigin) {
        return;
      }
      const data = event.data as Record<string, unknown> | null;
      if (!data || typeof data !== "object" || data.__shinsekai !== "plugin-host") {
        return;
      }
      if (
        data.type === "resize" &&
        surface === "section" &&
        typeof data.height === "number" &&
        Number.isFinite(data.height)
      ) {
        const clamped = Math.min(normalizedMaxHeight, Math.max(normalizedMinHeight, Math.ceil(data.height)));
        setSectionHeight(clamped);
        return;
      }
      if (data.type === "refresh" && Array.isArray(data.targets) && queryClient) {
        invalidatePluginRefreshTargets(
          queryClient,
          data.targets.map((item) => String(item)),
        );
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [normalizedMaxHeight, normalizedMinHeight, queryClient, surface, targetOrigin]);

  return (
    <iframe
      className={className}
      onLoad={() => pushStateToIframe(themeSnapshot, language)}
      ref={iframeRef}
      sandbox="allow-forms allow-same-origin allow-scripts"
      src={src}
      style={
        surface === "section" ? { height: `${sectionHeight}px`, minHeight: `${normalizedMinHeight}px` } : undefined
      }
      title={title}
    />
  );
}
