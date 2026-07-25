import { useQuery } from "@tanstack/react-query";
import { Info, Play, Puzzle, Settings, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";

import {
  listPluginSlotContributions,
  pluginSlotContributionsQueryKey,
  runPluginSlotContribution,
} from "../../entities/plugin/repository";
import type {
  PluginConfigGroupSchema,
  PluginSlotContribution,
  PluginSlotContributionIcon,
  PluginSlotId,
} from "../platform/types";
import { Button, useToast } from "../ui";
import { isPluginSlotId } from "./slotIds";
import "./PluginSlot.css";

export interface PluginRenderContext {
  contributionId: string;
  slot: PluginSlotId;
  title: string;
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
  contributions?: PluginUIContribution[];
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
    .map((item) => ({
      ...item,
      actionLabel: item.actionLabel.trim() || item.title.trim(),
      description: item.description.trim(),
      id: item.id.trim(),
      pluginId: item.pluginId.trim(),
      title: item.title.trim(),
    }))
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

const hostIcons: Record<PluginSlotContributionIcon, ReactNode> = {
  info: <Info aria-hidden className="button__icon" />,
  play: <Play aria-hidden className="button__icon" />,
  puzzle: <Puzzle aria-hidden className="button__icon" />,
  settings: <Settings aria-hidden className="button__icon" />,
  sparkles: <Sparkles aria-hidden className="button__icon" />,
};

function SerializableContribution({ contribution }: { contribution: PluginSlotContribution }) {
  const [running, setRunning] = useState(false);
  const { showToast } = useToast();
  const run = async () => {
    if (!contribution.actionable || running) {
      return;
    }
    setRunning(true);
    try {
      const result = await runPluginSlotContribution(contribution.pluginId, contribution.id);
      showToast({
        kind: result.kind,
        message: result.message || undefined,
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

  if (contribution.slot === "chat-output") {
    return (
      <article className="plugin-slot__output">
        <span className="plugin-slot__output-icon">{hostIcons[contribution.icon]}</span>
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

  return (
    <Button
      className={contribution.slot === "chat-dialog-actions" ? "dialog-stage-controls__button" : ""}
      disabled={!contribution.actionable}
      icon={hostIcons[contribution.icon]}
      loading={running}
      onClick={() => void run()}
      title={contribution.description || contribution.title}
      variant={contribution.variant}
    >
      {contribution.actionLabel}
    </Button>
  );
}

function ConnectedPluginSlot({ slot }: { slot: PluginSlotId }) {
  const query = useQuery({
    queryFn: listPluginSlotContributions,
    queryKey: pluginSlotContributionsQueryKey,
    retry: false,
    staleTime: 30_000,
  });
  const items = normalizeSerializablePluginContributions(query.data ?? []).filter((item) => item.slot === slot);
  if (!items.length) {
    return null;
  }
  return (
    <div className="plugin-slot" data-plugin-slot={slot}>
      {items.map((item) => (
        <div
          data-plugin-contribution={item.id}
          data-plugin-id={item.pluginId}
          data-plugin-title={item.title}
          key={`${item.pluginId}:${item.id}`}
        >
          <SerializableContribution contribution={item} />
        </div>
      ))}
    </div>
  );
}

export function PluginSlot({ contributions, slot }: PluginSlotProps) {
  if (contributions === undefined) {
    return <ConnectedPluginSlot slot={slot} />;
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
