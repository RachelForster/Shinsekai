import type { RelationNode } from "../../../shared/platform/types";
import type { Point } from "../model/graphLayout";
import type { GraphTheme } from "../model/graphTheme";
import { normalizeRelationName } from "../model/relationSelection";

const cache = new WeakMap<HTMLCanvasElement, Map<string, string>>();

function avatarSymbol(image: HTMLCanvasElement, borderColor: string, background: string, borderWidth: number) {
  const key = JSON.stringify([borderColor, background, borderWidth]);
  const cached = cache.get(image)?.get(key);
  if (cached) return cached;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const context = canvas.getContext("2d");
    if (!context) return undefined;
    context.beginPath();
    context.arc(64, 64, 64, 0, Math.PI * 2);
    context.fillStyle = borderColor;
    context.fill();
    const radius = 64 - borderWidth * 2;
    context.beginPath();
    context.arc(64, 64, radius, 0, Math.PI * 2);
    context.clip();
    context.fillStyle = background;
    context.fillRect(0, 0, 128, 128);
    context.drawImage(image, 64 - radius, 64 - radius, radius * 2, radius * 2);
    const symbol = `image://${canvas.toDataURL()}`;
    const entries = cache.get(image) ?? new Map<string, string>();
    entries.set(key, symbol);
    cache.set(image, entries);
    return symbol;
  } catch {
    return undefined;
  }
}

export function composeGraphNode({
  node,
  position,
  owner,
  activeNodeKey,
  selectedNodeKey,
  fixed,
  backgroundColor,
  theme,
  characterColors,
  avatars,
}: {
  node: RelationNode;
  position: Point;
  owner: string;
  activeNodeKey: string;
  selectedNodeKey: string;
  fixed: boolean;
  backgroundColor: string;
  theme: Pick<GraphTheme, "accent" | "selected" | "muted">;
  characterColors: ReadonlyMap<string, string>;
  avatars: ReadonlyMap<string, HTMLCanvasElement>;
}) {
  const name = normalizeRelationName(node.key);
  const borderColor = node.key === selectedNodeKey ? characterColors.get(name) || theme.accent : theme.muted;
  const borderWidth = node.key === activeNodeKey || node.key === owner ? 4 : 2;
  const fill = node.key === activeNodeKey ? theme.selected : backgroundColor;
  const avatar = avatars.get(name);
  const symbol = avatar ? avatarSymbol(avatar, borderColor, fill, borderWidth) : undefined;
  return {
    symbol: symbol ?? "circle",
    id: node.key,
    name: node.key,
    x: position.x,
    y: position.y,
    fixed,
    itemStyle: { color: fill, borderColor, borderWidth: symbol ? 0 : borderWidth },
  };
}
