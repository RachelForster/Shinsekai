import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { Maximize, Minus, Plus, LayoutGrid } from "lucide-react";
import { useI18n } from "../../../shared/i18n";
import { Button } from "../../../shared/ui";
import type { StoryGraph } from "../../../shared/platform/storyPreviewTypes";
import { layoutStoryGraph } from "../graph/layout";
import { nodeTypeLabels } from "./StoryNodeForm";
import "./StoryCanvas.css";

type Point = { x: number; y: number };
const WIDTH = 248;
const HEIGHT = 148;
const curve = (a: Point, b: Point, lane = 0) => {
  const bend = Math.max(70, Math.abs(b.x - a.x) / 2);
  return `M ${a.x} ${a.y} C ${a.x + bend} ${a.y + lane}, ${b.x - bend} ${b.y + lane}, ${b.x} ${b.y}`;
};

export function StoryCanvas({
  graph,
  selectedId,
  onSelect,
  onConnect,
  disabled,
  storageKey,
}: {
  graph: StoryGraph;
  selectedId: string;
  onSelect: (id: string, inspect?: boolean) => void;
  onConnect: (from: string, to: string) => void;
  disabled: boolean;
  storageKey: string;
}) {
  const { t } = useI18n();
  const viewport = useRef<HTMLDivElement>(null);
  const [positions, setPositions] = useState<Record<string, Point>>(() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
      return Object.fromEntries(
        Object.entries(value).filter((entry): entry is [string, Point] => {
          const point = entry[1] as Point | null;
          return Boolean(point && Number.isFinite(point.x) && Number.isFinite(point.y));
        }),
      );
    } catch {
      return {};
    }
  });
  const [view, setView] = useState({ x: 40, y: 40, scale: 1 });
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [wire, setWire] = useState<{ from: string; end: Point } | null>(null);
  const drag = useRef<{ id?: string; start: Point; origin: Point; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const nodes = useMemo(
    () =>
      layoutStoryGraph(graph).nodes.map((node) => ({
        ...node,
        ...(positions[node.id] ?? { x: node.x * 1.4, y: node.y * 1.5 }),
      })),
    [graph, positions],
  );
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const ids = graph.nodes.map((node) => node.id).join("\0");
  const fit = useCallback(() => {
    const items = nodesRef.current;
    if (!items.length) return;
    const left = Math.min(...items.map((n) => n.x));
    const top = Math.min(...items.map((n) => n.y));
    const width = Math.max(...items.map((n) => n.x + WIDTH)) - left;
    const height = Math.max(...items.map((n) => n.y + HEIGHT)) - top;
    const scale = Math.min(1.1, (size.width - 80) / width, (size.height - 100) / height);
    setView({
      scale: Math.max(0.001, scale),
      x: (size.width - width * scale) / 2 - left * scale,
      y: (size.height - height * scale) / 2 - top * scale,
    });
  }, [size]);
  useEffect(() => {
    const element = viewport.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width && entry.contentRect.height)
        setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    fit();
  }, [fit, ids]);
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(positions));
    } catch {
      /* Optional layout cache. */
    }
  }, [positions, storageKey]);
  const zoom = (factor: number, point = { x: size.width / 2, y: size.height / 2 }) => {
    setView((current) => {
      const scale = Math.min(2, Math.max(0.001, current.scale * factor));
      const ratio = scale / current.scale;
      return { scale, x: point.x - (point.x - current.x) * ratio, y: point.y - (point.y - current.y) * ratio };
    });
  };
  const localPoint = (event: { clientX: number; clientY: number }) => {
    const rect = viewport.current!.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - view.x) / view.scale,
      y: (event.clientY - rect.top - view.y) / view.scale,
    };
  };
  const begin = (event: PointerEvent, id?: string) => {
    if (event.button !== 0 && event.button !== 1) return;
    if (wire) {
      setWire(null);
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (id) onSelect(id, false);
    const node = nodes.find((n) => n.id === id);
    drag.current = { id, start: { x: event.clientX, y: event.clientY }, origin: node ?? view, moved: false };
    viewport.current?.setPointerCapture?.(event.pointerId);
  };
  const connect = (to: string) => {
    if (wire && wire.from !== to && !disabled) onConnect(wire.from, to);
    setWire(null);
  };
  return (
    <div
      className="story-canvas"
      ref={viewport}
      tabIndex={0}
      aria-label={t("story.canvas.title")}
      onKeyDown={(event) => {
        if (event.target instanceof HTMLElement && event.target.closest("input, textarea, select")) return;
        if (event.key.toLowerCase() === "f") {
          event.preventDefault();
          fit();
        }
        if (event.key === "Escape" && wire) {
          event.stopPropagation();
          setWire(null);
        }
      }}
      onWheel={(event) => {
        const rect = viewport.current!.getBoundingClientRect();
        zoom(Math.exp(-event.deltaY * 0.0015), { x: event.clientX - rect.left, y: event.clientY - rect.top });
      }}
      onPointerDown={(event) => begin(event)}
      onPointerMove={(event) => {
        if (wire) setWire({ ...wire, end: localPoint(event) });
        const current = drag.current;
        if (!current) return;
        const dx = event.clientX - current.start.x,
          dy = event.clientY - current.start.y;
        current.moved ||= Math.abs(dx) + Math.abs(dy) > 4;
        if (current.id)
          setPositions((previous) => ({
            ...previous,
            [current.id!]: {
              x: current.origin.x + dx / view.scale,
              y: current.origin.y + dy / view.scale,
            },
          }));
        else setView((previous) => ({ ...previous, x: current.origin.x + dx, y: current.origin.y + dy }));
      }}
      onPointerUp={(event) => {
        suppressClick.current = Boolean(drag.current?.moved);
        drag.current = null;
        viewport.current?.releasePointerCapture?.(event.pointerId);
        if (wire) {
          const target = document
            .elementFromPoint?.(event.clientX, event.clientY)
            ?.closest<HTMLElement>("[data-input]");
          if (target?.dataset.input) connect(target.dataset.input);
        }
      }}
      onPointerCancel={() => {
        drag.current = null;
        setWire(null);
      }}
      style={{
        backgroundPosition: `${view.x}px ${view.y}px`,
        backgroundSize: `${Math.max(12, 24 * view.scale)}px ${Math.max(12, 24 * view.scale)}px`,
      }}
    >
      <div
        className="story-canvas__world"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
      >
        <svg className="story-canvas__wires" aria-hidden>
          {nodes.flatMap((node) =>
            [
              ...(node.transitions ?? []).map((edge) => ({ ...edge, fallback: false })),
              ...(node.defaultTo
                ? [{ to: node.defaultTo, when: t("story.editor.defaultTarget"), fallback: true }]
                : []),
            ].map((edge, index) => {
              const target = nodes.find((n) => n.id === edge.to);
              if (!target) return null;
              return (
                <path
                  key={`${node.id}-${index}`}
                  className={edge.fallback ? "is-fallback" : ""}
                  d={curve({ x: node.x + WIDTH, y: node.y + 58 }, { x: target.x, y: target.y + 58 }, index * 32)}
                >
                  <title>{edge.when}</title>
                </path>
              );
            }),
          )}
          {wire &&
            (() => {
              const source = nodes.find((node) => node.id === wire.from);
              return source ? (
                <path className="is-pending" d={curve({ x: source.x + WIDTH, y: source.y + 58 }, wire.end)} />
              ) : null;
            })()}
        </svg>
        {nodes.map((node) => (
          <article
            key={node.id}
            data-node-id={node.id}
            className={`story-canvas__node ${node.type} ${node.id === selectedId ? "is-selected" : ""}`}
            style={{ left: node.x, top: node.y, width: WIDTH, height: HEIGHT }}
            onPointerDown={(event) => begin(event, node.id)}
          >
            <button
              className="story-canvas__node-heading"
              aria-pressed={node.id === selectedId}
              aria-label={`${t(nodeTypeLabels[node.type])} ${node.title || node.id}`}
              onClick={() => {
                if (!suppressClick.current) onSelect(node.id);
                suppressClick.current = false;
              }}
            >
              <small>
                {t(nodeTypeLabels[node.type])}
                {node.id === graph.startNodeId ? ` · ${t("story.editor.start")}` : ""}
              </small>
              <strong>{node.title || node.id}</strong>
            </button>
            <p>{node.instruction || t("story.canvas.empty")}</p>
            <footer>
              {node.id} <span>{(node.transitions?.length ?? 0) + (node.defaultTo ? 1 : 0)} ↗</span>
            </footer>
            <button
              className="story-canvas__port story-canvas__port--in"
              data-input={node.id}
              aria-label={t("story.canvas.input", { title: node.title })}
              disabled={disabled}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => connect(node.id)}
            />
            {node.type !== "ending_node" && (
              <button
                className="story-canvas__port story-canvas__port--out"
                aria-label={t("story.canvas.output", { title: node.title })}
                disabled={disabled}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  if (event.button === 0) setWire({ from: node.id, end: localPoint(event) });
                }}
                onClick={() => setWire({ from: node.id, end: { x: node.x + WIDTH + 80, y: node.y + 58 } })}
              />
            )}
          </article>
        ))}
      </div>
      <div className="story-canvas__controls" onPointerDown={(event) => event.stopPropagation()}>
        <Button title={t("story.canvas.fit")} aria-label={t("story.canvas.fit")} onClick={fit}>
          <Maximize size={16} />
        </Button>
        <Button
          title={t("story.canvas.arrange")}
          aria-label={t("story.canvas.arrange")}
          onClick={() => {
            setPositions({});
            requestAnimationFrame(() => fit());
          }}
        >
          <LayoutGrid size={16} />
        </Button>
        <Button aria-label={t("story.graph.zoomOut")} onClick={() => zoom(0.8)}>
          <Minus size={16} />
        </Button>
        <output>{Math.round(view.scale * 100)}%</output>
        <Button aria-label={t("story.graph.zoomIn")} onClick={() => zoom(1.25)}>
          <Plus size={16} />
        </Button>
      </div>
      <p className="story-canvas__hint">{t(wire ? "story.canvas.connectHint" : "story.canvas.hint")}</p>
    </div>
  );
}
