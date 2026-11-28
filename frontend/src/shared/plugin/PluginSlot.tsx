import { useQuery } from "@tanstack/react-query";
import { MoreHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useInRouterContext, useNavigate, type NavigateFunction } from "react-router-dom";

import {
  listPluginSlotContributions,
  pluginSlotContributionsQueryKey,
  runPluginSlotContribution,
} from "../../entities/plugin/repository";
import { useOptionalI18n } from "../i18n";
import type {
  PluginActionRunContext,
  PluginConfigGroupSchema,
  PluginSlotContribution,
  PluginSlotContributionPageMode,
  PluginSlotId,
} from "../platform/types";
import { Button, useOptionalToast } from "../ui";
import { hasUseQueryExport, useOptionalQueryClient } from "./optionalQueryClient";
import { localizePluginSlotContribution, resolveLocalizedText } from "./pluginI18n";
import { renderPluginIcon } from "./pluginIcons";
import { invalidatePluginRefreshTargets } from "./pluginRefresh";
import { isPluginSlotId } from "./slotIds";
import "./PluginSlot.css";

export interface PluginRenderContext {
  contributionId: string;
  slot: PluginSlotId;
  title: string;
}

export interface PluginPageTarget {
  mode?: PluginSlotContributionPageMode;
  pageId: string;
  payload?: Record<string, unknown>;
  pluginId: string;
  presentationId?: string;
}

/** Trusted in-process contribution kept for host-owned extensions and compatibility. */
export interface PluginUIContribution {
  configSchema?: PluginConfigGroupSchema[];
  icon?: ReactNode;
  id: string;
  permissions: string[];
  render: (context: PluginRenderContext) => ReactNode;
  slot: PluginSlotId;
  title: string;
}

interface PluginSlotProps {
  context?: PluginActionRunContext;
  contributions?: PluginUIContribution[];
  maxInline?: number;
  onOpenPluginPage?: (target: PluginPageTarget) => void;
  onLaunchConversation?: (id: string) => Promise<void>;
  slot: PluginSlotId;
}

export function normalizePluginContributions(contributions: PluginUIContribution[]): PluginUIContribution[] {
  const seen = new Set<string>();
  const normalized: PluginUIContribution[] = [];

  for (const contribution of contributions) {
    const id = contribution.id.trim();
    const title = contribution.title.trim();
    if (!id || !title || !isPluginSlotId(contribution.slot) || seen.has(id)) {
      continue;
    }
    seen.add(id);
    normalized.push({
      ...contribution,
      id,
      permissions: [...contribution.permissions],
      title,
    });
  }

  return normalized;
}

export function normalizeSerializablePluginContributions(
  contributions: PluginSlotContribution[],
): PluginSlotContribution[] {
  const seen = new Set<string>();
  return contributions
    .map(
      (item): PluginSlotContribution => ({
        ...item,
        actionLabel: item.actionLabel.trim() || item.title.trim(),
        actionType:
          item.actionType === "open-plugin-page" || item.actionType === "callback"
            ? item.actionType
            : item.actionable
              ? "callback"
              : "none",
        description: item.description.trim(),
        id: item.id.trim(),
        pageId: item.pageId?.trim() ?? "",
        pageMode: item.pageMode === "overlay" ? "overlay" : "navigate",
        pluginId: item.pluginId.trim(),
        presentation: item.presentation === "icon-only" ? "icon-only" : "button",
        title: item.title.trim(),
      }),
    )
    .filter((item) => {
      const key = `${item.pluginId}:${item.id}`;
      if (!item.id || !item.pluginId || !item.title || !isPluginSlotId(item.slot) || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .sort((left, right) => left.order - right.order || left.title.localeCompare(right.title));
}

function usePluginContributionRunner({
  context,
  contribution,
  navigate,
  onLaunchConversation,
  onOpenPluginPage,
}: {
  context?: PluginActionRunContext;
  contribution: PluginSlotContribution;
  navigate?: NavigateFunction;
  onLaunchConversation?: (id: string) => Promise<void>;
  onOpenPluginPage?: (target: PluginPageTarget) => void;
}) {
  const [running, setRunning] = useState(false);
  const queryClient = useOptionalQueryClient();
  const { language } = useOptionalI18n();
  const { showToast } = useOptionalToast();

  const canRun =
    contribution.actionable &&
    (contribution.actionType === "callback" ||
      (contribution.actionType === "open-plugin-page" &&
        Boolean(contribution.pageId) &&
        Boolean(onOpenPluginPage || navigate)));

  const run = async () => {
    if (!contribution.actionable || running) {
      return;
    }
    if (contribution.actionType === "open-plugin-page") {
      if (!contribution.pageId) {
        return;
      }
      if (onOpenPluginPage) {
        onOpenPluginPage({ mode: contribution.pageMode, pageId: contribution.pageId, pluginId: contribution.pluginId });
      } else if (navigate) {
        navigate(
          `/settings/plugins/${encodeURIComponent(contribution.pluginId)}/${encodeURIComponent(contribution.pageId)}`,
        );
      }
      return;
    }
    if (contribution.actionType !== "callback") {
      return;
    }
    setRunning(true);
    try {
      const runContext = context ? { ...context, locale: context.locale ?? language } : undefined;
      const result = runContext
        ? await runPluginSlotContribution(contribution.pluginId, contribution.id, runContext)
        : await runPluginSlotContribution(contribution.pluginId, contribution.id);
      if (queryClient) {
        invalidatePluginRefreshTargets(queryClient, result.refresh);
      }
      if (result.conversationId && onLaunchConversation) {
        await onLaunchConversation(result.conversationId);
        return;
      }
      const message = resolveLocalizedText(result.i18nMessage, language, result.message);
      showToast({
        kind: result.kind === "warning" ? "info" : result.kind,
        message: message || undefined,
        title: contribution.title,
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : undefined,
        title: contribution.title,
      });
    } finally {
      setRunning(false);
    }
  };

  return { canRun, run, running };
}

function SerializableContribution({
  context,
  contribution,
  navigate,
  onOpenPluginPage,
  onLaunchConversation,
}: {
  context?: PluginActionRunContext;
  contribution: PluginSlotContribution;
  navigate?: NavigateFunction;
  onOpenPluginPage?: (target: PluginPageTarget) => void;
  onLaunchConversation?: (id: string) => Promise<void>;
}) {
  const { canRun, run, running } = usePluginContributionRunner({
    context,
    contribution,
    navigate,
    onLaunchConversation,
    onOpenPluginPage,
  });

  if (contribution.slot === "chat-output") {
    return (
      <article className="plugin-slot__output">
        <span className="plugin-slot__output-icon">{renderPluginIcon(contribution.icon)}</span>
        <span className="plugin-slot__output-copy">
          <strong>{contribution.title}</strong>
          {contribution.description ? <small>{contribution.description}</small> : null}
        </span>
        {contribution.actionable ? (
          <Button loading={running} onClick={() => void run()} variant={contribution.variant}>
            {contribution.actionLabel}
          </Button>
        ) : null}
      </article>
    );
  }

  const iconOnly = contribution.presentation === "icon-only" || contribution.slot === "chat-top-toolbar";
  const className =
    contribution.slot === "chat-dialog-actions"
      ? "dialog-stage-controls__button"
      : contribution.slot === "chat-top-toolbar"
        ? "top-stage-tools__button plugin-slot__icon-button"
        : "";

  return (
    <Button
      aria-label={iconOnly ? contribution.title : undefined}
      className={className}
      disabled={!canRun}
      icon={renderPluginIcon(contribution.icon)}
      loading={running}
      onClick={() => void run()}
      tooltip={contribution.description || contribution.title}
      variant={contribution.variant}
    >
      {iconOnly ? null : contribution.actionLabel}
    </Button>
  );
}

function OverflowMenuItem({
  context,
  contribution,
  navigate,
  onDone,
  onLaunchConversation,
  onOpenPluginPage,
}: {
  context?: PluginActionRunContext;
  contribution: PluginSlotContribution;
  navigate?: NavigateFunction;
  onDone: () => void;
  onLaunchConversation?: (id: string) => Promise<void>;
  onOpenPluginPage?: (target: PluginPageTarget) => void;
}) {
  const { canRun, run, running } = usePluginContributionRunner({
    context,
    contribution,
    navigate,
    onLaunchConversation,
    onOpenPluginPage,
  });

  return (
    <button
      className="plugin-slot__more-item"
      disabled={!canRun || running}
      onClick={() => {
        onDone();
        void run();
      }}
      role="menuitem"
      title={contribution.description || contribution.title}
      type="button"
    >
      {renderPluginIcon(contribution.icon)}
      <span>{contribution.actionLabel || contribution.title}</span>
    </button>
  );
}

interface ConnectedPluginSlotProps {
  context?: PluginActionRunContext;
  maxInline?: number;
  navigate?: NavigateFunction;
  onOpenPluginPage?: (target: PluginPageTarget) => void;
  onLaunchConversation?: (id: string) => Promise<void>;
  slot: PluginSlotId;
}

function ConnectedPluginSlotInner({
  context,
  maxInline,
  navigate,
  onOpenPluginPage,
  onLaunchConversation,
  slot,
}: ConnectedPluginSlotProps) {
  const { language, t } = useOptionalI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement | null>(null);
  const hasContributionApi = typeof listPluginSlotContributions === "function";

  const query = useQuery({
    enabled: hasContributionApi,
    queryFn: () => listPluginSlotContributions(),
    queryKey: pluginSlotContributionsQueryKey,
    retry: false,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!menuOpen) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  const items = normalizeSerializablePluginContributions(query.data ?? [])
    .filter((item) => item.slot === slot)
    .map((item) => localizePluginSlotContribution(item, language));

  if (!items.length) {
    return null;
  }

  const shouldCollapse = maxInline !== undefined && maxInline > 0 && slot !== "chat-output" && items.length > maxInline;
  const inlineItems = shouldCollapse ? items.slice(0, maxInline) : items;
  const overflowItems = shouldCollapse ? items.slice(maxInline) : [];

  return (
    <div className="plugin-slot" data-plugin-slot={slot}>
      {inlineItems.map((item) => (
        <div
          data-plugin-contribution={item.id}
          data-plugin-id={item.pluginId}
          data-plugin-title={item.title}
          key={`${item.pluginId}:${item.id}`}
        >
          <SerializableContribution
            context={context}
            contribution={item}
            navigate={navigate}
            onOpenPluginPage={onOpenPluginPage}
            onLaunchConversation={onLaunchConversation}
          />
        </div>
      ))}
      {overflowItems.length ? (
        <div className="plugin-slot__more" ref={moreRef}>
          <Button
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            aria-label={t("plugin.slot.moreActions")}
            icon={<MoreHorizontal aria-hidden className="button__icon" />}
            onClick={() => setMenuOpen((open) => !open)}
            tooltip={t("plugin.slot.moreActions")}
            variant="ghost"
          />
          {menuOpen ? (
            <div className="plugin-slot__more-menu" role="menu">
              {overflowItems.map((item) => (
                <OverflowMenuItem
                  context={context}
                  contribution={item}
                  key={`${item.pluginId}:${item.id}`}
                  navigate={navigate}
                  onDone={() => setMenuOpen(false)}
                  onLaunchConversation={onLaunchConversation}
                  onOpenPluginPage={onOpenPluginPage}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function RouterPluginSlot(props: ConnectedPluginSlotProps) {
  const navigate = useNavigate();
  return <ConnectedPluginSlotInner {...props} navigate={navigate} />;
}

function QueryGuardedPluginSlot(props: ConnectedPluginSlotProps) {
  const inRouter = useInRouterContext();
  const queryClient = useOptionalQueryClient();
  if (!queryClient || !hasUseQueryExport()) {
    return null;
  }
  return inRouter ? <RouterPluginSlot {...props} /> : <ConnectedPluginSlotInner {...props} />;
}

export function PluginSlot({
  context,
  contributions,
  maxInline,
  onOpenPluginPage,
  onLaunchConversation,
  slot,
}: PluginSlotProps) {
  if (contributions === undefined) {
    return (
      <QueryGuardedPluginSlot
        context={context}
        maxInline={maxInline}
        onOpenPluginPage={onOpenPluginPage}
        onLaunchConversation={onLaunchConversation}
        slot={slot}
      />
    );
  }
  const items = normalizePluginContributions(contributions).filter((item) => item.slot === slot);
  if (!items.length) {
    return null;
  }

  return (
    <>
      {items.map((item) => (
        <div data-plugin-contribution={item.id} data-plugin-slot={slot} data-plugin-title={item.title} key={item.id}>
          {item.render({ contributionId: item.id, slot, title: item.title })}
        </div>
      ))}
    </>
  );
}
