import { useI18n } from "../../../shared/i18n";
import { Button, NumberInput, Select, TextArea, TextInput } from "../../../shared/ui";
import type { StoryGraph, StoryGraphNode } from "../../../shared/platform/storyPreviewTypes";

export const nodeTypeLabels = {
  limited_turn_node: "story.graph.limited",
  free_chat_node: "story.graph.free",
  ending_node: "story.graph.ending",
} as const;

export function StoryNodeForm({
  graph,
  node,
  disabled,
  onChange,
}: {
  graph: StoryGraph;
  node: StoryGraphNode;
  disabled: boolean;
  onChange: (node: StoryGraphNode) => void;
}) {
  const { t } = useI18n();
  const update = (patch: Partial<StoryGraphNode>) => onChange({ ...node, ...patch });
  return (
    <fieldset className="story-editor__fields" disabled={disabled}>
      <legend>{t("story.editor.node")}</legend>
      <label>
        {t("story.editor.nodeTitle")}
        <TextInput value={node.title} maxLength={200} onChange={(e) => update({ title: e.target.value })} />
      </label>
      <label>
        {t("story.editor.type")}
        <Select
          aria-label={t("story.editor.type")}
          disabled={disabled}
          value={node.type}
          onChange={(e) => {
            const type = e.target.value as StoryGraphNode["type"];
            const next = { ...node, type };
            delete next.maxRounds;
            if (type === "limited_turn_node") next.maxRounds = node.maxRounds ?? 3;
            if (type === "ending_node") {
              delete next.transitions;
              delete next.defaultTo;
            } else next.transitions ??= [];
            onChange(next);
          }}
        >
          {Object.entries(nodeTypeLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {t(label)}
            </option>
          ))}
        </Select>
      </label>
      <label>
        {t("story.editor.instruction")}
        <TextArea
          rows={8}
          value={node.instruction ?? ""}
          maxLength={8000}
          onChange={(e) => update({ instruction: e.target.value })}
        />
      </label>
      <p className="section__description">{t("story.editor.instructionHint")}</p>
      <label>
        {t("story.editor.background")}
        <TextInput value={node.background ?? ""} onChange={(e) => update({ background: e.target.value })} />
      </label>
      {node.type === "limited_turn_node" && (
        <label>
          {t("story.editor.rounds")}
          <NumberInput
            min={1}
            step={1}
            value={node.maxRounds ?? 3}
            onChange={(e) => update({ maxRounds: Number(e.target.value) })}
          />
        </label>
      )}
      {node.type !== "ending_node" && (
        <>
          <h3>{t("story.editor.transitions")}</h3>
          {(node.transitions ?? []).map((edge, index) => (
            <div className="story-editor__edge" key={index}>
              <label>
                {t("story.editor.target")}
                <Select
                  aria-label={t("story.editor.target")}
                  disabled={disabled}
                  value={edge.to}
                  onChange={(e) =>
                    update({
                      transitions: node.transitions?.map((item, i) =>
                        i === index ? { ...item, to: e.target.value } : item,
                      ),
                      defaultTo: node.defaultTo === edge.to ? e.target.value : node.defaultTo,
                    })
                  }
                >
                  <option value="">{t("story.editor.chooseTarget")}</option>
                  {graph.nodes.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title || item.id}
                    </option>
                  ))}
                </Select>
              </label>
              <label>
                {t("story.editor.condition")}
                <TextArea
                  rows={2}
                  maxLength={1000}
                  value={edge.when}
                  onChange={(e) =>
                    update({
                      transitions: node.transitions?.map((item, i) =>
                        i === index ? { ...item, when: e.target.value } : item,
                      ),
                    })
                  }
                />
              </label>
              <Button
                onClick={() => {
                  const transitions = node.transitions?.filter((_, i) => i !== index);
                  update({
                    transitions,
                    defaultTo: transitions?.some((item) => item.to === node.defaultTo) ? node.defaultTo : undefined,
                  });
                }}
              >
                {t("story.editor.removeEdge")}
              </Button>
            </div>
          ))}
          <Button onClick={() => update({ transitions: [...(node.transitions ?? []), { to: "", when: "" }] })}>
            {t("story.editor.addEdge")}
          </Button>
          {node.type === "limited_turn_node" && (
            <label>
              {t("story.editor.defaultTarget")}
              <Select
                aria-label={t("story.editor.defaultTarget")}
                disabled={disabled}
                value={node.defaultTo ?? ""}
                onChange={(e) => update({ defaultTo: e.target.value || undefined })}
              >
                <option value="">{t("story.editor.none")}</option>
                {[...new Set(node.transitions?.map((item) => item.to).filter(Boolean))].map((id) => (
                  <option key={id} value={id}>
                    {graph.nodes.find((item) => item.id === id)?.title || id}
                  </option>
                ))}
              </Select>
            </label>
          )}
        </>
      )}
    </fieldset>
  );
}
