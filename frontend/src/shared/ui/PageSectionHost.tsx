import { useEffect, useMemo, type ComponentType } from "react";

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
      resolveVisibleSections(sections, ctx).flatMap((section) =>
        section.navLabelKey ? [{ id: section.id, label: t(section.navLabelKey) }] : [],
      ),
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

/** Reports a section's active mutation/dialog busy state to pause page-level debounced auto-save. */
export function useReportSectionBusy(
  setSectionBusy: (sectionId: string, busy: boolean) => void,
  sectionId: string,
  busy: boolean,
) {
  useEffect(() => {
    setSectionBusy(sectionId, busy);
  }, [busy, sectionId, setSectionBusy]);

  useEffect(() => {
    return () => {
      setSectionBusy(sectionId, false);
    };
  }, [sectionId, setSectionBusy]);
}
