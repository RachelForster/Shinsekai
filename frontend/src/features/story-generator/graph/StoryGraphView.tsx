import { useI18n } from "../../../shared/i18n";
import { TRANSPARENT_BACKGROUND_NAME } from "../../../shared/constants";
import { Button } from "../../../shared/ui";
import { useId, useMemo, useState } from "react";
import type { StoryGraph } from "../../../shared/platform/storyPreviewTypes";
import { layoutStoryGraph, NODE_HEIGHT, NODE_WIDTH } from "./layout";
import "./StoryGraphView.css";

const nodeLabels = {
  limited_turn_node: "story.graph.limited",
  free_chat_node: "story.graph.free",
  ending_node: "story.graph.ending",
} as const;

export function StoryGraphView({ graph }: { graph: StoryGraph }) {
  const { t } = useI18n();
  const [selectedId, setSelectedId] = useState(graph.startNodeId);
  const [zoom, setZoom] = useState(1);
  const marker = useId().replace(/:/g, "");
  const layout = useMemo(() => layoutStoryGraph(graph), [graph]);
  const selected = graph.nodes.find((node) => node.id === selectedId) ?? graph.nodes[0];
  const title = (id: string) => graph.nodes.find((node) => node.id === id)?.title ?? id;
  const edges = layout.nodes.flatMap((node) => {
    const targets = new Set((node.transitions ?? []).map((item) => item.to));
    if (node.defaultTo) targets.add(node.defaultTo);
    return [...targets].flatMap((id) => {
      const target = layout.nodes.find((item) => item.id === id);
      if (!target) return [];
      const x = node.x + NODE_WIDTH,
        y = node.y + NODE_HEIGHT / 2;
      const endY = target.y + NODE_HEIGHT / 2;
      const path =
        target.x > node.x
          ? `M ${x} ${y} C ${x + 36} ${y}, ${target.x - 36} ${endY}, ${target.x - 6} ${endY}`
          : `M ${x} ${y} C ${x + 50} ${y - 100}, ${target.x - 40} ${endY - 100}, ${target.x - 6} ${endY}`;
      return [
        <path
          key={`${node.id}-${id}`}
          d={path}
          markerEnd={`url(#${marker})`}
          className={node.id === selected?.id ? "selected" : ""}
        >
          <title>
            {node.title} → {target.title}
          </title>
        </path>,
      ];
    });
  });
  return (
    <section className="section" aria-labelledby="story-graph-title">
      <div className="section__header story-graph__header">
        <div>
          <h2 className="section__title" id="story-graph-title">
            {t("story.graph.title")}
          </h2>
          <p className="section__description">{t("story.graph.hint")}</p>
        </div>
        <div className="story-graph__zoom" role="group" aria-label={t("story.graph.zoom")}>
          <Button
            type="button"
            aria-label={t("story.graph.zoomOut")}
            disabled={zoom <= 0.5}
            onClick={() => setZoom(zoom - 0.25)}
          >
            −
          </Button>
          <Button type="button" aria-label={t("story.graph.zoomReset")} onClick={() => setZoom(1)}>
            {Math.round(zoom * 100)}%
          </Button>
          <Button
            type="button"
            aria-label={t("story.graph.zoomIn")}
            disabled={zoom >= 1.5}
            onClick={() => setZoom(zoom + 0.25)}
          >
            +
          </Button>
        </div>
      </div>
      <div className="story-graph__scroll" tabIndex={0} role="region" aria-label={t("story.graph.region")}>
        <div style={{ width: layout.width * zoom, height: layout.height * zoom }}>
          <div
            className="story-graph__canvas"
            style={{ width: layout.width, height: layout.height, transform: `scale(${zoom})` }}
          >
            <svg width={layout.width} height={layout.height} aria-hidden="true">
              <defs>
                <marker
                  id={marker}
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                </marker>
              </defs>
              {edges}
            </svg>
            {layout.nodes.map((node) => (
              <button
                type="button"
                key={node.id}
                className={`story-graph__node story-graph__node--${node.type}`}
                style={{ left: node.x, top: node.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
                aria-pressed={selected?.id === node.id}
                onClick={() => setSelectedId(node.id)}
              >
                <small>
                  {node.id === graph.startNodeId ? t("story.graph.start") : ""}
                  {t(nodeLabels[node.type])}
                </small>
                <strong>{node.title || node.id}</strong>
              </button>
            ))}
          </div>
        </div>
      </div>
      {selected && (
        <article className="story-graph__detail" aria-label={t("story.graph.details")}>
          <h3>{selected.title}</h3>
          <p className="section__description">{selected.instruction || t("story.graph.endHint")}</p>
          {selected.background && (
            <p className="section__description">
              {t("story.graph.location", {
                background:
                  selected.background === TRANSPARENT_BACKGROUND_NAME
                    ? t("template.transparentBackground")
                    : selected.background,
              })}
            </p>
          )}
          {selected.maxRounds !== undefined && (
            <p className="section__description">{t("story.graph.rounds", { count: selected.maxRounds })}</p>
          )}
          <ul>
            {selected.transitions?.map((transition, index) => (
              <li key={`${transition.to}-${index}`}>
                {transition.when} →{" "}
                <Button variant="ghost" type="button" onClick={() => setSelectedId(transition.to)}>
                  {title(transition.to)}
                </Button>
              </li>
            ))}
          </ul>
          {selected.defaultTo && (
            <p className="section__description">{t("story.graph.default", { title: title(selected.defaultTo) })}</p>
          )}
        </article>
      )}
    </section>
  );
}
