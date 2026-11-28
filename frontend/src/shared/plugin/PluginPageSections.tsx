import { QueryClientContext, useMutation, useQuery, type QueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import {
  listPluginPageSections,
  pluginPageSectionsQueryKey,
  runPluginSectionAction,
  savePluginSectionValues,
} from "../../entities/plugin/repository";
import { useOptionalI18n } from "../i18n";
import type { PluginActionRunContext, PluginConfigAction, PluginSectionContribution } from "../platform/types";
import { AlertDialog, AsyncButton, SchemaDrivenForm, type PageSectionDescriptor, useOptionalToast } from "../ui";

const FALLBACK_QUERY_CLIENT_CONTEXT = createContext<QueryClient | undefined>(undefined);
import {
  pluginConfigGroupsToFormGroups,
  pluginConfigInitialValues,
  type PluginConfigDraft,
} from "./pluginConfigSchema";
import { localizePluginSection, resolveLocalizedText } from "./pluginI18n";
import { PluginIframeHost } from "./PluginIframeHost";
import { invalidatePluginRefreshTargets } from "./pluginRefresh";

export interface UsePluginPageSectionsOptions {
  enabled?: boolean;
  entityId?: string;
  entityType?: string;
  extra?: Record<string, unknown>;
  page: string;
}

export function pluginSectionDomId(section: Pick<PluginSectionContribution, "id" | "pluginId">): string {
  const safePlugin = section.pluginId.replace(/[^A-Za-z0-9_-]+/g, "-");
  const safeId = section.id.replace(/[^A-Za-z0-9_-]+/g, "-");
  return `plugin-section-${safePlugin}-${safeId}`;
}

export function usePluginPageSections({
  enabled = true,
  entityId,
  entityType,
  extra,
  page,
}: UsePluginPageSectionsOptions): PluginSectionContribution[] {
  const { language } = useOptionalI18n();
  const hasApi = typeof listPluginPageSections === "function";
  const queryKey =
    typeof pluginPageSectionsQueryKey === "function"
      ? pluginPageSectionsQueryKey(page, entityType, entityId)
      : ["plugins", "sections", page, entityType ?? "", entityId ?? ""];

  const query = useQuery({
    enabled: enabled && hasApi && Boolean(page),
    queryFn: () => listPluginPageSections({ entityId, entityType, extra, locale: language, page }),
    queryKey,
    retry: false,
    staleTime: 30_000,
  });

  return useMemo(() => (query.data ?? []).map((item) => localizePluginSection(item, language)), [language, query.data]);
}

function SchemaPluginSection({
  context,
  id,
  section,
}: {
  context?: PluginActionRunContext;
  id: string;
  section: PluginSectionContribution;
}) {
  const queryClient = useContext(QueryClientContext ?? FALLBACK_QUERY_CLIENT_CONTEXT);
  const { language, t } = useOptionalI18n();
  const { showToast } = useOptionalToast();
  const formGroups = useMemo(() => pluginConfigGroupsToFormGroups(section.schema ?? []), [section.schema]);
  const [draft, setDraft] = useState<PluginConfigDraft>(() => pluginConfigInitialValues(section));
  const [pendingAction, setPendingAction] = useState<PluginConfigAction | null>(null);

  useEffect(() => {
    setDraft(pluginConfigInitialValues(section));
  }, [section]);

  const resolvedContext: PluginActionRunContext = {
    ...context,
    locale: context?.locale ?? language,
    page: context?.page ?? section.page,
  };
  const sectionQueryKey =
    typeof pluginPageSectionsQueryKey === "function"
      ? pluginPageSectionsQueryKey(
          section.page,
          resolvedContext.entityType ?? undefined,
          resolvedContext.entityId ?? undefined,
        )
      : ["plugins", "sections", section.page];

  const saveMutation = useMutation({
    mutationFn: () => savePluginSectionValues(section.pluginId, section.id, draft, resolvedContext),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.section.saveFailed"),
        title: section.title,
      });
    },
    onSuccess(result) {
      if (result.section) {
        setDraft(pluginConfigInitialValues(result.section));
      }
      if (queryClient) {
        void queryClient.invalidateQueries({ queryKey: sectionQueryKey });
        invalidatePluginRefreshTargets(queryClient, result.refresh);
      }
      const message = resolveLocalizedText(result.i18nMessage, language, result.message) || t("plugin.section.saved");
      showToast({
        kind: result.kind === "warning" ? "info" : result.kind,
        message,
        title: section.title,
      });
    },
  });

  const actionMutation = useMutation({
    mutationFn: (action: PluginConfigAction) =>
      runPluginSectionAction(section.pluginId, section.id, action.id, draft, resolvedContext),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("plugin.section.saveFailed"),
        title: section.title,
      });
    },
    onSuccess(result) {
      if (result.section) {
        setDraft(pluginConfigInitialValues(result.section));
      }
      if (queryClient) {
        void queryClient.invalidateQueries({ queryKey: sectionQueryKey });
        invalidatePluginRefreshTargets(queryClient, result.refresh);
      }
      const message = resolveLocalizedText(result.i18nMessage, language, result.message);
      showToast({
        kind: result.kind === "warning" ? "info" : result.kind,
        message: message || undefined,
        title: section.title,
      });
    },
  });

  const actions = (section.actions ?? []).filter((action) => action.id);
  const canSave = section.canSave !== false;

  return (
    <section
      className="section page-section-anchor plugin-section-card"
      data-plugin-id={section.pluginId}
      data-plugin-section={section.id}
      id={id}
    >
      <div className="section__header">
        <div>
          <h2 className="section__title">{section.title}</h2>
          {section.description ? <p className="section__description">{section.description}</p> : null}
        </div>
      </div>
      {formGroups.length ? <SchemaDrivenForm groups={formGroups} onChange={setDraft} value={draft} /> : null}
      {actions.length || canSave ? (
        <div className="plugin-section-card__footer">
          {actions.map((action) => (
            <AsyncButton
              key={action.id}
              loading={actionMutation.isPending && actionMutation.variables?.id === action.id}
              onClick={() => {
                if (action.confirm) {
                  setPendingAction(action);
                } else {
                  actionMutation.mutate(action);
                }
              }}
              tooltip={action.description || undefined}
              variant={action.variant}
            >
              {action.label}
            </AsyncButton>
          ))}
          {canSave ? (
            <AsyncButton
              icon={<Save aria-hidden className="button__icon" />}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
              variant="primary"
            >
              {t("plugin.section.save")}
            </AsyncButton>
          ) : null}
        </div>
      ) : null}
      {pendingAction ? (
        <AlertDialog
          body={pendingAction.confirm ?? ""}
          cancelLabel={t("common.cancel")}
          confirmLabel={t("common.confirm")}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => {
            actionMutation.mutate(pendingAction);
            setPendingAction(null);
          }}
          open
          title={pendingAction.label}
        />
      ) : null}
    </section>
  );
}

function IframePluginSection({
  context,
  id,
  section,
}: {
  context?: PluginActionRunContext;
  id: string;
  section: PluginSectionContribution;
}) {
  const { t } = useOptionalI18n();
  return (
    <section
      className="section page-section-anchor plugin-section-frame-card"
      data-plugin-id={section.pluginId}
      data-plugin-section={section.id}
      id={id}
    >
      {section.title || section.description ? (
        <div className="section__header">
          <div>
            <h2 className="section__title">{section.title}</h2>
            {section.description ? <p className="section__description">{section.description}</p> : null}
          </div>
        </div>
      ) : null}
      {section.frontendUrl ? (
        <PluginIframeHost
          className="plugin-section__frame"
          context={context}
          frontendUrl={section.frontendUrl}
          maxHeight={section.maxHeight}
          minHeight={section.minHeight}
          pluginId={section.pluginId}
          slot={section.slot}
          surface="section"
          title={section.title}
        />
      ) : (
        <p className="inline-status">{t("plugin.section.unavailable")}</p>
      )}
    </section>
  );
}

export interface ToPageSectionDescriptorsOptions<TSlot extends string> {
  context?: PluginActionRunContext;
  defaultSlot?: TSlot;
  orderBase?: number;
  preserveDeclaredSlot?: boolean;
}

export function toPageSectionDescriptors<TCtx, TSlot extends string = "body">(
  sections: readonly PluginSectionContribution[],
  options: ToPageSectionDescriptorsOptions<TSlot> = {},
): PageSectionDescriptor<TCtx, TSlot>[] {
  const orderBase = options.orderBase ?? 1000;
  return sections.map((section, index) => {
    const id = pluginSectionDomId(section);
    const slot = options.preserveDeclaredSlot ? ((section.slot as TSlot) ?? options.defaultSlot) : options.defaultSlot;
    return {
      Component: ({ id: sectionId }) =>
        section.renderer === "iframe" ? (
          <IframePluginSection context={options.context} id={sectionId} section={section} />
        ) : (
          <SchemaPluginSection context={options.context} id={sectionId} section={section} />
        ),
      id,
      navLabel: section.navLabel || section.title,
      order: orderBase + section.order * 10 + index,
      slot,
    };
  });
}

export function usePluginPageSectionDescriptors<TCtx, TSlot extends string = "body">(
  query: UsePluginPageSectionsOptions,
  options: ToPageSectionDescriptorsOptions<TSlot> = {},
): PageSectionDescriptor<TCtx, TSlot>[] {
  const sections = usePluginPageSections(query);
  const contextJson = JSON.stringify(options.context ?? {});
  return useMemo(
    () =>
      toPageSectionDescriptors<TCtx, TSlot>(sections, {
        ...options,
        context: contextJson ? (JSON.parse(contextJson) as PluginActionRunContext) : undefined,
      }),
    [contextJson, options.defaultSlot, options.orderBase, options.preserveDeclaredSlot, sections],
  );
}
