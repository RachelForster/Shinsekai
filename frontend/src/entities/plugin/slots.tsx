import type { ReactNode } from "react";

import { isPluginSlotId } from "./types";
import type { PluginConfigGroupSchema, PluginSlotId } from "./types";

export interface PluginRenderContext {
  contributionId: string;
  slot: PluginSlotId;
  title: string;
}

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
  contributions?: PluginUIContribution[];
  slot: PluginSlotId;
}

export function normalizePluginContributions(
  contributions: PluginUIContribution[],
): PluginUIContribution[] {
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

export function PluginSlot({ contributions = [], slot }: PluginSlotProps) {
  const items = normalizePluginContributions(contributions).filter((item) => item.slot === slot);
  if (!items.length) {
    return null;
  }
  return (
    <>
      {items.map((item) => (
        <div
          data-plugin-contribution={item.id}
          data-plugin-slot={slot}
          data-plugin-title={item.title}
          key={item.id}
        >
          {item.render({ contributionId: item.id, slot, title: item.title })}
        </div>
      ))}
    </>
  );
}
