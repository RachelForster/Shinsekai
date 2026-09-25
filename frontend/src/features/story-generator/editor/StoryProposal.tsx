import { useI18n } from "../../../shared/i18n";
import { useEffect, useRef } from "react";
import { Button } from "../../../shared/ui";
import type { StoryGraph, StoryGraphNode } from "../../../shared/platform/storyPreviewTypes";
import type { StorySuggestion } from "../../../shared/platform/storyEditorTypes";
import { StoryGraphView } from "../graph/StoryGraphView";
import { nodeTypeLabels } from "./StoryNodeForm";

export function StoryProposal({
  before,
  proposal,
  onApply,
  onDiscard,
}: {
  before: StoryGraph;
  proposal: StorySuggestion;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const { t } = useI18n();
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, []);
  const title = (graph: StoryGraph, id: string) => graph.nodes.find((node) => node.id === id)?.title || id;
  const describe = (node: StoryGraphNode | undefined, graph: StoryGraph) =>
    node
      ? [
          node.title,
          t(nodeTypeLabels[node.type]),
          node.instruction,
          node.background ? `${t("story.editor.background")}: ${node.background}` : "",
          node.maxRounds != null ? `${t("story.editor.rounds")}: ${node.maxRounds}` : "",
          ...(node.transitions ?? []).map((edge) => `${edge.when} → ${title(graph, edge.to)}`),
          node.defaultTo ? `${t("story.editor.defaultTarget")}: ${title(graph, node.defaultTo)}` : "",
        ]
          .filter(Boolean)
          .join("\n")
      : t("story.editor.none");
  const ids = [...new Set([...before.nodes, ...proposal.graph.nodes].map((node) => node.id))];
  return (
    <section ref={panel} className="section story-editor__proposal" aria-label={t("story.editor.proposal")}>
      <h2>{t("story.editor.proposal")}</h2>
      <p>{proposal.summary}</p>
      {before.startNodeId !== proposal.graph.startNodeId && (
        <p>
          {t("story.editor.start")}: {title(before, before.startNodeId)} →{" "}
          {title(proposal.graph, proposal.graph.startNodeId)}
        </p>
      )}
      {ids.map((id) => {
        const oldNode = before.nodes.find((node) => node.id === id);
        const newNode = proposal.graph.nodes.find((node) => node.id === id);
        if (JSON.stringify(oldNode) === JSON.stringify(newNode)) return null;
        return (
          <details key={id} open className="story-editor__change">
            <summary>
              {newNode?.title || oldNode?.title} ·{" "}
              {t(!oldNode ? "story.editor.added" : !newNode ? "story.editor.removed" : "story.editor.changed")}
            </summary>
            <div className="story-editor__comparison">
              <div>
                <h3>{t("story.editor.before")}</h3>
                <p>{describe(oldNode, before)}</p>
              </div>
              <div>
                <h3>{t("story.editor.after")}</h3>
                <p>{describe(newNode, proposal.graph)}</p>
              </div>
            </div>
          </details>
        );
      })}
      <StoryGraphView graph={proposal.graph} />
      {!!proposal.validation.issues.length && (
        <ul>
          {proposal.validation.issues.map((issue, i) => (
            <li key={i}>{issue.message}</li>
          ))}
        </ul>
      )}
      <div className="story-editor__actions">
        <Button variant="primary" disabled={!proposal.validation.valid} onClick={onApply}>
          {t("story.editor.accept")}
        </Button>
        <Button onClick={onDiscard}>{t("story.editor.discard")}</Button>
      </div>
    </section>
  );
}
