import { useCallback, useMemo, useRef, useState, type ComponentType } from "react";
import type { DefaultError, UseMutationOptions } from "@tanstack/react-query";

import { useI18n, type MessageKey } from "../i18n";
import type { PageSectionNavItem } from "./PageSectionNav";

export interface PageSectionProps<TCtx> {
  ctx: TCtx;
  id: string;
}

export interface PageSectionDescriptor<TCtx, TSlot extends string = "body"> {
  id: string;
  order: number;
  slot?: TSlot;
  navLabel?: string;
  navLabelKey?: MessageKey;
  isVisible?: (ctx: TCtx) => boolean;
  Component: ComponentType<PageSectionProps<TCtx>>;
  validate?: (ctx: TCtx) => Record<string, string>;
  normalizeForSave?: (ctx: TCtx) => void;
}

export function resolveVisibleSections<TCtx, TSlot extends string = "body">(
  sections: readonly PageSectionDescriptor<TCtx, TSlot>[],
  ctx: TCtx,
  slot?: TSlot,
): PageSectionDescriptor<TCtx, TSlot>[] {
  return sections
    .filter((section) => {
      if (slot !== undefined && (section.slot ?? "body") !== slot) {
        return false;
      }
      return section.isVisible ? section.isVisible(ctx) : true;
    })
    .slice()
    .sort((left, right) => left.order - right.order);
}

export function useVisibleSectionNavItems<TCtx, TSlot extends string = "body">(
  sections: readonly PageSectionDescriptor<TCtx, TSlot>[],
  ctx: TCtx,
): PageSectionNavItem[] {
  const { t } = useI18n();

  return useMemo(
    () =>
      resolveVisibleSections(sections, ctx).flatMap((section) => {
        const label = section.navLabelKey ? t(section.navLabelKey) : section.navLabel;
        return label ? [{ id: section.id, label }] : [];
      }),
    [ctx, sections, t],
  );
}

export interface PageSectionHostProps<TCtx, TSlot extends string = "body"> {
  ctx: TCtx;
  sections: readonly PageSectionDescriptor<TCtx, TSlot>[];
  slot?: TSlot;
}

export function PageSectionHost<TCtx, TSlot extends string = "body">({
  ctx,
  sections,
  slot,
}: PageSectionHostProps<TCtx, TSlot>) {
  const visibleSections = resolveVisibleSections(sections, ctx, slot);

  return (
    <>
      {visibleSections.map((section) => {
        const SectionComponent = section.Component;
        return <SectionComponent ctx={ctx} id={section.id} key={section.id} />;
      })}
    </>
  );
}

export interface SectionBusyLease {
  release: () => void;
  settled: Promise<void>;
}

export interface UseSectionBusyRegistryOptions {
  onBeforeBusy?: () => Promise<void> | void;
}

export interface SectionBusyRegistry {
  beginSectionBusy: (sectionId: string) => SectionBusyLease;
  busyCount: number;
  resumeRevision: number;
  setSectionBusy: (key: string, busy: boolean) => void;
}

/** Tracks busy section mutations and modal states while discarding/draining autosave synchronously. */
export function useSectionBusyRegistry({ onBeforeBusy }: UseSectionBusyRegistryOptions = {}): SectionBusyRegistry {
  const onBeforeBusyRef = useRef(onBeforeBusy);
  onBeforeBusyRef.current = onBeforeBusy;
  const leaseCountRef = useRef(0);
  const busyFlagsRef = useRef<Set<string>>(new Set());
  const [busyCount, setBusyCount] = useState(0);
  const [resumeRevision, setResumeRevision] = useState(0);

  const syncBusyCount = useCallback((shouldMarkResume = false) => {
    const nextCount = leaseCountRef.current + busyFlagsRef.current.size;
    setBusyCount(nextCount);
    if (shouldMarkResume && nextCount === 0) {
      setResumeRevision((current) => current + 1);
    }
  }, []);

  const beginSectionBusy = useCallback(
    (_sectionId: string): SectionBusyLease => {
      leaseCountRef.current += 1;
      syncBusyCount();
      const pendingBeforeBusy = onBeforeBusyRef.current?.();
      const settled = Promise.resolve(pendingBeforeBusy).catch(() => undefined);
      let released = false;
      return {
        release: () => {
          if (released) {
            return;
          }
          released = true;
          leaseCountRef.current = Math.max(0, leaseCountRef.current - 1);
          syncBusyCount(true);
        },
        settled,
      };
    },
    [syncBusyCount],
  );

  const setSectionBusy = useCallback(
    (key: string, busy: boolean) => {
      if (busy) {
        void onBeforeBusyRef.current?.();
        if (!busyFlagsRef.current.has(key)) {
          busyFlagsRef.current.add(key);
          syncBusyCount();
        }
        return;
      }
      if (busyFlagsRef.current.delete(key)) {
        syncBusyCount(true);
      }
    },
    [syncBusyCount],
  );

  return {
    beginSectionBusy,
    busyCount,
    resumeRevision,
    setSectionBusy,
  };
}

/** Wraps TanStack Query mutation options to acquire a synchronous busy lease before mutationFn runs. */
export function withSectionBusy<TData = unknown, TError = DefaultError, TVariables = void>(
  beginSectionBusy: (sectionId: string) => SectionBusyLease,
  sectionId: string,
  options: Omit<UseMutationOptions<TData, TError, TVariables, SectionBusyLease>, "onMutate">,
): UseMutationOptions<TData, TError, TVariables, SectionBusyLease> {
  const { onSettled, ...rest } = options;
  return {
    ...rest,
    async onMutate() {
      const lease = beginSectionBusy(sectionId);
      await lease.settled;
      return lease;
    },
    onSettled(data, error, variables, lease, context) {
      lease?.release();
      return onSettled?.(data, error, variables, lease, context);
    },
  };
}
