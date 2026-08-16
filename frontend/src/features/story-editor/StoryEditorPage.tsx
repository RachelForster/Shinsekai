import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  getStoryProject,
  getStoryProjectGraph,
  patchStoryProject,
  previewStoryCast,
  previewStoryPath,
  proposeStoryAiPatch,
  publishStoryProject,
  undoStoryProject,
  validateStoryProject,
} from "../../entities/story/repository";
import type {
  StoryAiPatchProposal,
  StoryCastPreview,
  StoryGenerationValidation,
  StoryGraphProjection,
  StoryPatchOperation,
  StoryPathPreview,
  StoryProjectDocument,
} from "../../entities/story/types";
import { useI18n } from "../../shared/i18n";
import type { MessageKey } from "../../shared/i18n";
import { StoryGraphCanvas } from "./StoryGraphCanvas";
import "./StoryEditorPage.css";

type StoryObject = Record<string, unknown>;

const emptyGraph: StoryGraphProjection = {
  diagnostics: [],
  narrative: { edges: [], nodes: [] },
  rules: { edges: [], nodes: [] },
  sourceMap: {},
};

function asObject(value: unknown): StoryObject {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as StoryObject) : {};
}

function asArray(value: unknown): StoryObject[] {
  return Array.isArray(value)
    ? value.filter((item): item is StoryObject => Boolean(item) && typeof item === "object")
    : [];
}

function asTextList(value: unknown) {
  return Array.isArray(value) ? value.map(String) : [];
}

function pointer(value: string) {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function decodePointerToken(token: string) {
  return token.replaceAll("~1", "/").replaceAll("~0", "~");
}

function readPointer(root: unknown, path: string): unknown {
  if (!path || path === "/") return root;
  let current: unknown = root;
  for (const token of path.split("/").slice(1).map(decodePointerToken)) {
    if (Array.isArray(current) && /^\d+$/.test(token)) {
      current = current[Number(token)];
      continue;
    }
    if (current && typeof current === "object" && !Array.isArray(current) && token in current) {
      current = (current as StoryObject)[token];
      continue;
    }
    return undefined;
  }
  return current;
}

function appendOperations(root: unknown, parentPath: string, value: unknown): StoryPatchOperation[] {
  const operations: StoryPatchOperation[] = [];
  if (!Array.isArray(readPointer(root, parentPath))) {
    operations.push({ op: "add", path: parentPath, value: [] });
  }
  operations.push({ op: "add", path: `${parentPath}/-`, value });
  return operations;
}

function nextIndexedId(existing: Iterable<string>, prefix: string) {
  const used = new Set(existing);
  let next = 1;
  while (used.has(`${prefix}${next}`)) {
    next += 1;
  }
  return `${prefix}${next}`;
}

function initialCastPolicy() {
  return {
    mode: "fixed",
    required: [],
    constraints: { minActive: 0, maxActive: 8, preserveCurrentCast: true },
    fallback: { onMissingRole: "error", onLoadFailure: "error" },
  };
}

function nodeTypeLabel(type: string, t: (key: MessageKey) => string) {
  if (type === "ending") return t("story.editor.nodeType.ending");
  if (type === "story") return t("story.editor.nodeType.story");
  return type;
}

function enterWhenText(value: unknown) {
  const item = asObject(value);
  const gte = item.gte;
  if (Array.isArray(gte) && gte.length >= 2) {
    return `${String(gte[0])} >= ${String(gte[1])}`;
  }
  return "";
}

export function StoryEditorPage() {
  const { t } = useI18n();
  const { storyId = "" } = useParams();
  const [document, setDocument] = useState<StoryProjectDocument | null>(null);
  const [graph, setGraph] = useState<StoryGraphProjection>(emptyGraph);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [validation, setValidation] = useState<StoryGenerationValidation | null>(null);
  const [castPreview, setCastPreview] = useState<StoryCastPreview | null>(null);
  const [pathPreview, setPathPreview] = useState<StoryPathPreview | null>(null);
  const [proposal, setProposal] = useState<StoryAiPatchProposal | null>(null);
  const [aiInstruction, setAiInstruction] = useState("");
  const [effectTarget, setEffectTarget] = useState("");
  const [effectAmount, setEffectAmount] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const source = document?.source ?? {};
  const narrative = asObject(source.narrativeGraph);
  const nodes = asArray(narrative.nodes);
  const variables = asObject(source.variables);
  const cast = asObject(source.cast);
  const characters = asArray(cast.characters);
  const signals = asArray(source.semanticSignals);
  const ruleGraph = asObject(source.logicGraph);
  const ruleNodes = asArray(ruleGraph.nodes);
  const selectedNodeIndex = nodes.findIndex((node) => node.id === selectedNodeId);
  const selectedNode = selectedNodeIndex >= 0 ? nodes[selectedNodeIndex] : null;
  const endings = nodes.filter((node) => node.type === "ending");

  const selectNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setCastPreview(null);
  };

  const refresh = async () => {
    if (!storyId) return;
    const [nextDocument, nextGraph] = await Promise.all([getStoryProject(storyId), getStoryProjectGraph(storyId)]);
    setDocument(nextDocument);
    setGraph(nextGraph);
    setValidation(nextDocument.validation);
    const startNode = asObject(nextDocument.source.narrativeGraph).startNodeId;
    setSelectedNodeId(
      (current) =>
        current || String(startNode || asArray(asObject(nextDocument.source.narrativeGraph).nodes)[0]?.id || ""),
    );
  };

  useEffect(() => {
    setBusy(true);
    refresh()
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setBusy(false));
  }, [storyId]);

  const commit = async (operations: StoryPatchOperation[], allowInvalid = true) => {
    if (!document || !storyId || !operations.length) return;
    setBusy(true);
    setError("");
    try {
      const result = await patchStoryProject({
        id: storyId,
        baseRevision: document.manifest.draftRevision,
        commit: true,
        allowInvalid,
        patch: { operations },
      });
      if (result.document) {
        setDocument(result.document);
        setValidation(result.document.validation);
      }
      setGraph(await getStoryProjectGraph(storyId));
      setProposal(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const updateNode = (key: string, value: unknown) => {
    if (selectedNodeIndex < 0) return;
    void commit([{ op: "replace", path: `/narrativeGraph/nodes/${selectedNodeIndex}/${key}`, value }]);
  };

  const updateCastPolicy = (next: StoryObject) => {
    if (selectedNodeIndex < 0) return;
    void commit([{ op: "replace", path: `/narrativeGraph/nodes/${selectedNodeIndex}/castPolicy`, value: next }]);
  };

  const addNode = () => {
    const id = nextIndexedId(
      nodes.map((node) => String(node.id || "")),
      "scene-",
    );
    const index = Number(id.slice("scene-".length));
    void commit([
      {
        op: "add",
        path: "/narrativeGraph/nodes/-",
        value: {
          id,
          title: t("story.editor.newScene", { index }),
          commitment: "draft",
          castPolicy: initialCastPolicy(),
          choices: [],
          freeformIntents: [],
        },
      },
    ]).then(() => setSelectedNodeId(id));
  };

  const addChoice = () => {
    if (selectedNodeIndex < 0) return;
    const id = nextIndexedId(
      asArray(selectedNode?.choices).map((choice) => String(choice.id || "")),
      "choice-",
    );
    const index = Number(id.slice("choice-".length));
    void commit(
      appendOperations(source, `/narrativeGraph/nodes/${selectedNodeIndex}/choices`, {
        id,
        label: t("story.editor.newChoice", { index }),
        goto: "",
        effects: [],
        when: { true: [] },
      }),
    );
  };

  const addEffect = () => {
    if (selectedNodeIndex < 0 || !effectTarget.trim()) return;
    void commit(
      appendOperations(source, `/narrativeGraph/nodes/${selectedNodeIndex}/onEnter`, {
        increment: [effectTarget.trim(), Number(effectAmount) || 0],
      }),
    );
  };

  const addVariable = () => {
    const id = nextIndexedId(Object.keys(variables), "state.variable_");
    void commit([
      {
        op: "add",
        path: `/variables/${pointer(id)}`,
        value: { type: "integer", initial: 0, min: 0, max: 100, visible: true, allowSemanticInput: false },
      },
    ]);
  };

  const addSignal = () => {
    const id = nextIndexedId(
      signals.map((signal) => String(signal.id || "")),
      "signal-",
    );
    void commit(
      appendOperations(source, "/semanticSignals", {
        id,
        minimumConfidence: "medium",
        allowedSpeechActs: ["endorsement"],
        repeatWindow: 20,
        maxPerTurn: 1,
        maxPerScene: 2,
        maxPerChapter: 6,
        effectsByStrength: { weak: [], medium: [], strong: [] },
      }),
    );
  };

  const addCharacter = () => {
    const id = nextIndexedId(
      characters.map((character) => String(character.id || "")),
      "character-",
    );
    void commit(
      appendOperations(source, "/cast/characters", {
        id,
        source: { path: `characters/${id}.yaml` },
        tags: [],
        roles: [],
        priority: 0,
      }),
    );
  };

  const addRuleNode = () => {
    const id = nextIndexedId(
      ruleNodes.map((node) => String(node.id || "")),
      "rule-",
    );
    void commit(appendOperations(source, "/logicGraph/nodes", { id, type: "story-start", config: {} }));
  };

  const undo = async () => {
    if (!document || !storyId) return;
    setBusy(true);
    try {
      const next = await undoStoryProject(storyId, document.manifest.draftRevision);
      setDocument(next);
      setValidation(next.validation);
      setGraph(await getStoryProjectGraph(storyId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const validate = async () => {
    if (!storyId) return;
    setBusy(true);
    try {
      setValidation(await validateStoryProject(storyId));
      setGraph(await getStoryProjectGraph(storyId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const inspectCast = async () => {
    if (!storyId || !selectedNodeId) return;
    setBusy(true);
    try {
      setCastPreview(await previewStoryCast({ id: storyId, nodeId: selectedNodeId }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const previewEnding = async (endingId: string) => {
    if (!storyId) return;
    setBusy(true);
    try {
      setPathPreview(await previewStoryPath({ id: storyId, endingId }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const askAi = async () => {
    if (!document || !storyId || !selectedNodeId || !aiInstruction.trim()) return;
    setBusy(true);
    try {
      setProposal(
        await proposeStoryAiPatch({
          id: storyId,
          baseRevision: document.manifest.draftRevision,
          region: `node:${selectedNodeId}`,
          instruction: aiInstruction,
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const applyProposal = () => {
    if (!proposal) return;
    void commit(proposal.patch.operations, false);
  };

  const publish = async () => {
    if (!document || !storyId) return;
    setBusy(true);
    try {
      const result = await publishStoryProject(storyId, document.manifest.draftRevision);
      setError(
        t(
          result.saveCompatibility.compatibleWithPrevious
            ? "story.editor.publishCompatible"
            : "story.editor.publishBreaking",
          { version: result.version },
        ),
      );
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const castPolicy = asObject(selectedNode?.castPolicy);
  const castConstraints = asObject(castPolicy.constraints);

  if (!storyId) {
    return (
      <main className="story-editor-page">
        <p>{t("story.editor.missingId")}</p>
      </main>
    );
  }

  return (
    <main className="story-editor-page">
      <header className="story-editor-header">
        <div>
          <Link to="/settings/stories/new">{t("story.editor.backToGenerator")}</Link>
          <p className="story-editor-eyebrow">{t("story.editor.eyebrow")}</p>
          <h1>{document?.manifest.title ?? t("story.editor.loading")}</h1>
          <p>
            {t("story.editor.draftPublished", {
              revision: document?.manifest.draftRevision ?? 0,
              version: document?.manifest.publishedVersion ?? 0,
            })}
          </p>
        </div>
        <div className="story-editor-actions">
          <button disabled={busy || !document} onClick={undo} type="button">
            {t("story.editor.undo")}
          </button>
          <button disabled={busy || !document} onClick={validate} type="button">
            {t("story.editor.validate")}
          </button>
          <button
            className="primary"
            disabled={busy || !document || validation?.valid === false}
            onClick={publish}
            type="button"
          >
            {t("story.editor.publish")}
          </button>
        </div>
      </header>

      {error ? (
        <p className="story-editor-notice" role="status">
          {error}
        </p>
      ) : null}

      <section className="story-editor-layout">
        <aside className="story-editor-sidebar">
          <div className="story-editor-section-title">
            <h2>{t("story.editor.nodes")}</h2>
            <button disabled={busy} onClick={addNode} type="button">
              {t("story.editor.addNode")}
            </button>
          </div>
          <nav aria-label={t("story.editor.nodes")}>
            {nodes.map((node) => (
              <button
                className={node.id === selectedNodeId ? "selected" : ""}
                key={String(node.id)}
                onClick={() => selectNode(String(node.id))}
                type="button"
              >
                <span>{String(node.title || node.id)}</span>
                <small>{nodeTypeLabel(String(node.type || "story"), t)}</small>
              </button>
            ))}
          </nav>
          <div className="story-editor-section-title">
            <h2>{t("story.editor.endings")}</h2>
          </div>
          {endings.map((node) => (
            <button
              className="text-button"
              disabled={busy}
              key={String(node.id)}
              onClick={() => previewEnding(String(node.id))}
              type="button"
            >
              {t("story.editor.previewEnding", { title: String(node.title || node.id) })}
            </button>
          ))}
        </aside>

        <section className="story-editor-workspace">
          {selectedNode ? (
            <article className="story-editor-card" key={String(selectedNode.id)}>
              <div className="story-editor-section-title">
                <h2>{t("story.editor.selectedNode")}</h2>
                <code>{String(selectedNode.id)}</code>
              </div>
              <label>
                {t("story.editor.nodeTitle")}
                <input
                  onBlur={(event) => updateNode("title", event.target.value)}
                  defaultValue={String(selectedNode.title || "")}
                />
              </label>
              <div className="story-editor-two-col">
                <label>
                  {t("story.editor.nodeType")}
                  <select
                    value={String(selectedNode.type || "story")}
                    onChange={(event) => updateNode("type", event.target.value)}
                  >
                    <option value="story">{t("story.editor.nodeType.story")}</option>
                    <option value="ending">{t("story.editor.nodeType.ending")}</option>
                  </select>
                </label>
                <label>
                  {t("story.editor.commitment")}
                  <select
                    value={String(selectedNode.commitment || "draft")}
                    onChange={(event) => updateNode("commitment", event.target.value)}
                  >
                    <option value="draft">{t("story.editor.commitment.draft")}</option>
                    <option value="committed">{t("story.editor.commitment.committed")}</option>
                    <option value="frozen">{t("story.editor.commitment.frozen")}</option>
                  </select>
                </label>
              </div>
              <fieldset>
                <legend>{t("story.editor.enterCondition")}</legend>
                <label>
                  {t("story.editor.enterWhen")}
                  <input
                    defaultValue={enterWhenText(selectedNode.enterWhen)}
                    placeholder={t("story.editor.enterWhenPlaceholder")}
                    onBlur={(event) => {
                      const match = event.target.value.trim().match(/^([^\s]+)\s*>=\s*(-?\d+)$/);
                      updateNode("enterWhen", match ? { gte: [match[1], Number(match[2])] } : { true: [] });
                    }}
                  />
                </label>
              </fieldset>
              <fieldset>
                <legend>{t("story.editor.enterEffects")}</legend>
                <div className="story-editor-inline">
                  <input
                    placeholder={t("story.editor.variableId")}
                    value={effectTarget}
                    onChange={(event) => setEffectTarget(event.target.value)}
                  />
                  <input
                    aria-label={t("story.editor.effectAmount")}
                    type="number"
                    value={effectAmount}
                    onChange={(event) => setEffectAmount(event.target.value)}
                  />
                  <button disabled={busy || !effectTarget.trim()} onClick={addEffect} type="button">
                    {t("story.editor.addEffect")}
                  </button>
                </div>
                <p>{t("story.editor.effectCount", { count: asArray(selectedNode.onEnter).length })}</p>
              </fieldset>
              <fieldset>
                <legend>{t("story.editor.choices")}</legend>
                {asArray(selectedNode.choices).map((choice, choiceIndex) => (
                  <div className="story-editor-choice" key={String(choice.id)}>
                    <input
                      aria-label={t("story.editor.choiceLabel", { index: choiceIndex + 1 })}
                      defaultValue={String(choice.label || "")}
                      onBlur={(event) =>
                        void commit([
                          {
                            op: "replace",
                            path: `/narrativeGraph/nodes/${selectedNodeIndex}/choices/${choiceIndex}/label`,
                            value: event.target.value,
                          },
                        ])
                      }
                    />
                    <select
                      aria-label={t("story.editor.choiceGoto", { index: choiceIndex + 1 })}
                      value={String(choice.goto || "")}
                      onChange={(event) =>
                        void commit([
                          {
                            op: "replace",
                            path: `/narrativeGraph/nodes/${selectedNodeIndex}/choices/${choiceIndex}/goto`,
                            value: event.target.value,
                          },
                        ])
                      }
                    >
                      <option value="">{t("story.editor.choiceTarget")}</option>
                      {nodes.map((node) => (
                        <option key={String(node.id)} value={String(node.id)}>
                          {String(node.title || node.id)}
                        </option>
                      ))}
                    </select>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void commit([
                          { op: "remove", path: `/narrativeGraph/nodes/${selectedNodeIndex}/choices/${choiceIndex}` },
                        ])
                      }
                      type="button"
                    >
                      {t("story.editor.delete")}
                    </button>
                  </div>
                ))}
                <button disabled={busy} onClick={addChoice} type="button">
                  {t("story.editor.addChoice")}
                </button>
              </fieldset>
            </article>
          ) : (
            <article className="story-editor-card">
              <p>{t("story.editor.selectNode")}</p>
            </article>
          )}

          <article className="story-editor-card">
            <div className="story-editor-section-title">
              <h2>{t("story.editor.castTitle")}</h2>
              <button disabled={busy || !selectedNode} onClick={inspectCast} type="button">
                {t("story.editor.castPreview")}
              </button>
            </div>
            {selectedNode ? (
              <>
                <div className="story-editor-two-col">
                  <label>
                    {t("story.editor.castMode")}
                    <select
                      value={String(castPolicy.mode || "fixed")}
                      onChange={(event) =>
                        updateCastPolicy({ ...initialCastPolicy(), ...castPolicy, mode: event.target.value })
                      }
                    >
                      <option value="fixed">{t("story.editor.castMode.fixed")}</option>
                      <option value="mixed">{t("story.editor.castMode.mixed")}</option>
                      <option value="role-based">{t("story.editor.castMode.roleBased")}</option>
                      <option value="dynamic">{t("story.editor.castMode.dynamic")}</option>
                    </select>
                  </label>
                  <label>
                    {t("story.editor.maxActive")}
                    <input
                      type="number"
                      min="0"
                      value={Number(castConstraints.maxActive ?? 8)}
                      onChange={(event) =>
                        updateCastPolicy({
                          ...initialCastPolicy(),
                          ...castPolicy,
                          constraints: { ...castConstraints, maxActive: Number(event.target.value) },
                        })
                      }
                    />
                  </label>
                </div>
                <label>
                  {t("story.editor.castRequired")}
                  <input
                    value={asTextList(castPolicy.required).join(", ")}
                    onChange={(event) =>
                      updateCastPolicy({
                        ...initialCastPolicy(),
                        ...castPolicy,
                        required: event.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </label>
              </>
            ) : null}
            <div className="story-editor-chip-list">
              {characters.map((character, index) => (
                <div key={String(character.id)}>
                  <strong>{String(character.id)}</strong>
                  <input
                    aria-label={`${String(character.id)} roles`}
                    defaultValue={asTextList(character.roles).join(", ")}
                    onBlur={(event) =>
                      void commit([
                        {
                          op: "replace",
                          path: `/cast/characters/${index}/roles`,
                          value: event.target.value
                            .split(",")
                            .map((item) => item.trim())
                            .filter(Boolean),
                        },
                      ])
                    }
                  />
                  <input
                    aria-label={`${String(character.id)} tags`}
                    defaultValue={asTextList(character.tags).join(", ")}
                    onBlur={(event) =>
                      void commit([
                        {
                          op: "replace",
                          path: `/cast/characters/${index}/tags`,
                          value: event.target.value
                            .split(",")
                            .map((item) => item.trim())
                            .filter(Boolean),
                        },
                      ])
                    }
                  />
                  <button
                    disabled={busy}
                    onClick={() => void commit([{ op: "remove", path: `/cast/characters/${index}` }])}
                    type="button"
                  >
                    {t("story.editor.remove")}
                  </button>
                </div>
              ))}
            </div>
            <button disabled={busy} onClick={addCharacter} type="button">
              {t("story.editor.addCharacter")}
            </button>
            {castPreview ? (
              <div className="story-editor-preview">
                <p>
                  {castPreview.valid
                    ? t("story.editor.castSelected", {
                        ids: castPreview.activeCharacterIds.join("、") || t("story.editor.castEmpty"),
                      })
                    : castPreview.error?.message}
                </p>
                <ul>
                  {castPreview.candidates.map((candidate) => (
                    <li key={candidate.characterId}>
                      {candidate.characterId}: {candidate.reasonCode}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </article>

          <article className="story-editor-card">
            <div className="story-editor-section-title">
              <h2>{t("story.editor.variablesTitle")}</h2>
              <div>
                <button disabled={busy} onClick={addVariable} type="button">
                  {t("story.editor.addVariable")}
                </button>
                <button disabled={busy} onClick={addSignal} type="button">
                  {t("story.editor.addSignal")}
                </button>
                <button disabled={busy} onClick={addRuleNode} type="button">
                  {t("story.editor.addRule")}
                </button>
              </div>
            </div>
            <div className="story-editor-table">
              <h3>{t("story.editor.variables")}</h3>
              {Object.entries(variables).map(([id, definition]) => {
                const item = asObject(definition);
                return (
                  <div key={id}>
                    <code>{id}</code>
                    <select
                      value={String(item.type || "integer")}
                      onChange={(event) =>
                        void commit([
                          { op: "replace", path: `/variables/${pointer(id)}/type`, value: event.target.value },
                        ])
                      }
                    >
                      <option value="integer">{t("story.editor.variableType.integer")}</option>
                      <option value="boolean">{t("story.editor.variableType.boolean")}</option>
                      <option value="enum">{t("story.editor.variableType.enum")}</option>
                      <option value="string_set">{t("story.editor.variableType.stringSet")}</option>
                    </select>
                    <input
                      aria-label={`${id} initial`}
                      defaultValue={String(item.initial ?? "")}
                      onBlur={(event) =>
                        void commit([
                          {
                            op: "replace",
                            path: `/variables/${pointer(id)}/initial`,
                            value: item.type === "integer" ? Number(event.target.value) : event.target.value,
                          },
                        ])
                      }
                    />
                    <button
                      disabled={busy}
                      onClick={() => void commit([{ op: "remove", path: `/variables/${pointer(id)}` }])}
                      type="button"
                    >
                      {t("story.editor.delete")}
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="story-editor-table">
              <h3>{t("story.editor.signals")}</h3>
              {signals.map((signal, index) => (
                <div key={String(signal.id)}>
                  <input
                    aria-label={t("story.editor.signalId", { index: index + 1 })}
                    defaultValue={String(signal.id || "")}
                    onBlur={(event) =>
                      void commit([{ op: "replace", path: `/semanticSignals/${index}/id`, value: event.target.value }])
                    }
                  />
                  <select
                    value={String(signal.minimumConfidence || "medium")}
                    onChange={(event) =>
                      void commit([
                        {
                          op: "replace",
                          path: `/semanticSignals/${index}/minimumConfidence`,
                          value: event.target.value,
                        },
                      ])
                    }
                  >
                    <option value="low">{t("story.editor.confidence.low")}</option>
                    <option value="medium">{t("story.editor.confidence.medium")}</option>
                    <option value="high">{t("story.editor.confidence.high")}</option>
                  </select>
                  <button
                    disabled={busy}
                    onClick={() => void commit([{ op: "remove", path: `/semanticSignals/${index}` }])}
                    type="button"
                  >
                    {t("story.editor.delete")}
                  </button>
                </div>
              ))}
            </div>
            <div className="story-editor-table">
              <h3>{t("story.editor.rules")}</h3>
              {ruleNodes.map((node, index) => (
                <div key={String(node.id)}>
                  <code>{String(node.id)}</code>
                  <input
                    aria-label={t("story.editor.ruleType", { index: index + 1 })}
                    defaultValue={String(node.type || "")}
                    onBlur={(event) =>
                      void commit([
                        { op: "replace", path: `/logicGraph/nodes/${index}/type`, value: event.target.value },
                      ])
                    }
                  />
                  <button
                    disabled={busy}
                    onClick={() => void commit([{ op: "remove", path: `/logicGraph/nodes/${index}` }])}
                    type="button"
                  >
                    {t("story.editor.delete")}
                  </button>
                </div>
              ))}
            </div>
          </article>

          <article className="story-editor-card">
            <div className="story-editor-section-title">
              <h2>{t("story.editor.aiTitle")}</h2>
              <button disabled={busy || !selectedNode || !aiInstruction.trim()} onClick={askAi} type="button">
                {t("story.editor.aiGenerate")}
              </button>
            </div>
            <textarea
              aria-label={t("story.editor.aiInstruction")}
              value={aiInstruction}
              onChange={(event) => setAiInstruction(event.target.value)}
              placeholder={t("story.editor.aiPlaceholder")}
              rows={3}
            />
            {proposal ? (
              <div className="story-editor-proposal">
                <p>
                  {t("story.editor.aiProposal", {
                    count: proposal.diff.length,
                    status: t(
                      proposal.validation.valid ? "story.editor.validationPassed" : "story.editor.validationFailed",
                    ),
                  })}
                </p>
                <ul>
                  {proposal.diff.map((item) => (
                    <li key={item.path}>
                      {item.op} {item.path}
                    </li>
                  ))}
                </ul>
                <button
                  className="primary"
                  disabled={busy || !proposal.validation.valid}
                  onClick={applyProposal}
                  type="button"
                >
                  {t("story.editor.aiApply")}
                </button>
              </div>
            ) : null}
          </article>
        </section>

        <aside className="story-editor-inspector">
          <section className="story-editor-card">
            <h2>{t("story.editor.graphTitle")}</h2>
            <StoryGraphCanvas graph={graph} onSelectNode={selectNode} selectedNodeId={selectedNodeId} />
            <h3>{t("story.editor.sourceMap")}</h3>
            <ul className="story-editor-source-map">
              {Object.entries(graph.sourceMap)
                .slice(0, 14)
                .map(([key, value]) => (
                  <li key={key}>
                    <code>{key}</code>
                    <span>{value}</span>
                  </li>
                ))}
            </ul>
          </section>
          <section className="story-editor-card">
            <h2>{t("story.editor.diagnostics")}</h2>
            <Diagnostics validation={validation} />
          </section>
          {pathPreview ? (
            <section className="story-editor-card">
              <h2>{t("story.editor.pathPreview")}</h2>
              <p>
                <code>{pathPreview.branchId}</code>
              </p>
              <p>{t("story.editor.finalNode", { id: String(pathPreview.finalState.currentNodeId || "-") })}</p>
              <ol>
                {pathPreview.snapshots.map((snapshot) => (
                  <li key={snapshot.step}>
                    {t("story.editor.step", {
                      step: snapshot.step,
                      action: String(snapshot.action.type || "start"),
                    })}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
        </aside>
      </section>
    </main>
  );
}

function Diagnostics({ validation }: { validation: StoryGenerationValidation | null }) {
  const { t } = useI18n();
  if (!validation) return <p>{t("story.editor.diagnosticsLoading")}</p>;
  if (!validation.issues.length) return <p className="story-editor-valid">{t("story.editor.diagnosticsPass")}</p>;
  return (
    <ul className="story-editor-diagnostics">
      {validation.issues.map((issue) => (
        <li className={issue.severity} key={`${issue.code}-${issue.path}`}>
          <strong>{issue.code}</strong>
          <span>{issue.message}</span>
          <code>{issue.path}</code>
        </li>
      ))}
    </ul>
  );
}
