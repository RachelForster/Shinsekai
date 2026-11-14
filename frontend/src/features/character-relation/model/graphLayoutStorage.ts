import type { Point, Positions } from "./graphLayout";

const storageKey = (owner: string): string => `character-relation-layout:v1:${owner}`;

function isGraphPoint(value: unknown): value is Point {
  if (!value || typeof value !== "object") return false;
  const point = value as Partial<Point>;
  return Number.isFinite(point.x) && Number.isFinite(point.y);
}

export function readPositions(owner: string): Positions {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey(owner)) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, point]) => isGraphPoint(point)));
  } catch {
    return {};
  }
}

export function savePositions(owner: string, positions: Positions): void {
  try {
    localStorage.setItem(storageKey(owner), JSON.stringify(positions));
  } catch {
    /* Layout remains usable without storage. */
  }
}
