import { useEffect, useMemo, useState } from "react";
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

export function StoryEditorPage() {
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
          title: `新场景 ${index}`,
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
        label: `选择 ${index}`,
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
        source: { type: "author-generated", path: `characters/${id}.yaml` },
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
    void commit(
      appendOperations(source, "/logicGraph/nodes", { id, type: "story-start", config: {} }),
    );
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
        `已发布 v${result.version} · ${result.saveCompatibility.compatibleWithPrevious ? "存档兼容" : "含破坏性变更"}`,
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
        <p>缺少剧本 ID。</p>
      </main>
    );
  }

  return (
    <main className="story-editor-page">
      <header className="story-editor-header">
        <div>
          <Link to="/settings/stories/new">← 剧本生成器</Link>
          <p className="story-editor-eyebrow">STORY CREATOR</p>
          <h1>{document?.manifest.title ?? "加载剧本…"}</h1>
          <p>
            草稿 r{document?.manifest.draftRevision ?? 0} · 已发布 v{document?.manifest.publishedVersion ?? 0}
          </p>
        </div>
        <div className="story-editor-actions">
          <button disabled={busy || !document} onClick={undo} type="button">
            撤销
          </button>
          <button disabled={busy || !document} onClick={validate} type="button">
            发布前校验
          </button>
          <button
            className="primary"
            disabled={busy || !document || validation?.valid === false}
            onClick={publish}
            type="button"
          >
            发布版本
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
            <h2>剧情节点</h2>
            <button disabled={busy} onClick={addNode} type="button">
              + 节点
            </button>
          </div>
          <nav aria-label="剧情节点">
            {nodes.map((node) => (
              <button
                className={node.id === selectedNodeId ? "selected" : ""}
                key={String(node.id)}
                onClick={() => setSelectedNodeId(String(node.id))}
                type="button"
              >
                <span>{String(node.title || node.id)}</span>
                <small>{String(node.type || "story")}</small>
              </button>
            ))}
          </nav>
          <div className="story-editor-section-title">
            <h2>结局试演</h2>
          </div>
          {endings.map((node) => (
            <button
              className="text-button"
              disabled={busy}
              key={String(node.id)}
              onClick={() => previewEnding(String(node.id))}
              type="button"
            >
              试演 {String(node.title || node.id)}
            </button>
          ))}
        </aside>

        <section className="story-editor-workspace">
          {selectedNode ? (
            <article className="story-editor-card">
              <div className="story-editor-section-title">
                <h2>场景与节点</h2>
                <code>{String(selectedNode.id)}</code>
              </div>
              <label>
                标题
                <input
                  onBlur={(event) => updateNode("title", event.target.value)}
                  defaultValue={String(selectedNode.title || "")}
                />
              </label>
              <div className="story-editor-two-col">
                <label>
                  节点类型
                  <select
                    value={String(selectedNode.type || "story")}
                    onChange={(event) => updateNode("type", event.target.value)}
                  >
                    <option value="story">剧情场景</option>
                    <option value="ending">结局</option>
                  </select>
                </label>
                <label>
                  承诺边界
                  <select
                    value={String(selectedNode.commitment || "draft")}
                    onChange={(event) => updateNode("commitment", event.target.value)}
                  >
                    <option value="draft">草稿</option>
                    <option value="committed">已承诺</option>
                    <option value="frozen">冻结</option>
                  </select>
                </label>
              </div>
              <fieldset>
                <legend>进入条件</legend>
                <label>
                  变量阈值（留空表示总是可进入）
                  <input
                    placeholder="例如 trust.ling >= 10"
                    onBlur={(event) => {
                      const match = event.target.value.trim().match(/^([^\s]+)\s*>=\s*(-?\d+)$/);
                      updateNode("enterWhen", match ? { gte: [match[1], Number(match[2])] } : { true: [] });
                    }}
                  />
                </label>
              </fieldset>
              <fieldset>
                <legend>进入效果</legend>
                <div className="story-editor-inline">
                  <input
                    placeholder="变量 ID"
                    value={effectTarget}
                    onChange={(event) => setEffectTarget(event.target.value)}
                  />
                  <input
                    aria-label="效果增量"
                    type="number"
                    value={effectAmount}
                    onChange={(event) => setEffectAmount(event.target.value)}
                  />
                  <button disabled={busy || !effectTarget.trim()} onClick={addEffect} type="button">
                    添加增量
                  </button>
                </div>
                <p>当前效果：{asArray(selectedNode.onEnter).length} 条</p>
              </fieldset>
              <fieldset>
                <legend>结构化选项</legend>
                {asArray(selectedNode.choices).map((choice, choiceIndex) => (
                  <div className="story-editor-choice" key={String(choice.id)}>
                    <input
                      aria-label={`选项 ${choiceIndex + 1} 文案`}
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
                      aria-label={`选项 ${choiceIndex + 1} 目标`}
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
                      <option value="">选择目标节点</option>
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
                      删除
                    </button>
                  </div>
                ))}
                <button disabled={busy} onClick={addChoice} type="button">
                  + 添加选择
                </button>
              </fieldset>
            </article>
          ) : (
            <article className="story-editor-card">
              <p>选择一个节点开始编辑。</p>
            </article>
          )}

          <article className="story-editor-card">
            <div className="story-editor-section-title">
              <h2>演员表与 CastPolicy</h2>
              <button disabled={busy || !selectedNode} onClick={inspectCast} type="button">
                预览演员表
              </button>
            </div>
            {selectedNode ? (
              <>
                <div className="story-editor-two-col">
                  <label>
                    模式
                    <select
                      value={String(castPolicy.mode || "fixed")}
                      onChange={(event) =>
                        updateCastPolicy({ ...initialCastPolicy(), ...castPolicy, mode: event.target.value })
                      }
                    >
                      <option value="fixed">固定</option>
                      <option value="mixed">混合</option>
                      <option value="role-based">职责驱动</option>
                      <option value="dynamic">动态候选</option>
                    </select>
                  </label>
                  <label>
                    最大活跃人数
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
                  固定角色（以逗号分隔）
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
                    移除
                  </button>
                </div>
              ))}
            </div>
            <button disabled={busy} onClick={addCharacter} type="button">
              + 人物
            </button>
            {castPreview ? (
              <div className="story-editor-preview">
                <p>
                  {castPreview.valid
                    ? `已选：${castPreview.activeCharacterIds.join("、") || "无人"}`
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
              <h2>变量、语义信号与规则</h2>
              <div>
                <button disabled={busy} onClick={addVariable} type="button">
                  + 变量
                </button>
                <button disabled={busy} onClick={addSignal} type="button">
                  + 信号
                </button>
                <button disabled={busy} onClick={addRuleNode} type="button">
                  + 规则节点
                </button>
              </div>
            </div>
            <div className="story-editor-table">
              <h3>变量</h3>
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
                      <option value="integer">整数</option>
                      <option value="boolean">布尔</option>
                      <option value="enum">枚举</option>
                      <option value="string_set">字符串集合</option>
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
                      删除
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="story-editor-table">
              <h3>语义信号</h3>
              {signals.map((signal, index) => (
                <div key={String(signal.id)}>
                  <input
                    aria-label={`信号 ${index + 1} ID`}
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
                    <option value="low">低</option>
                    <option value="medium">中</option>
                    <option value="high">高</option>
                  </select>
                  <button
                    disabled={busy}
                    onClick={() => void commit([{ op: "remove", path: `/semanticSignals/${index}` }])}
                    type="button"
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
            <div className="story-editor-table">
              <h3>逻辑图节点</h3>
              {ruleNodes.map((node, index) => (
                <div key={String(node.id)}>
                  <code>{String(node.id)}</code>
                  <input
                    aria-label={`规则 ${index + 1} 类型`}
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
                    删除
                  </button>
                </div>
              ))}
            </div>
          </article>

          <article className="story-editor-card">
            <div className="story-editor-section-title">
              <h2>AI 局部重生与差异</h2>
              <button disabled={busy || !selectedNode || !aiInstruction.trim()} onClick={askAi} type="button">
                生成补丁
              </button>
            </div>
            <textarea
              aria-label="AI 修改说明"
              value={aiInstruction}
              onChange={(event) => setAiInstruction(event.target.value)}
              placeholder="例如：强化这一场景的抉择，但保持现有节点 ID 和所有已承诺事实。"
              rows={3}
            />
            {proposal ? (
              <div className="story-editor-proposal">
                <p>
                  候选补丁：{proposal.diff.length} 项差异，{proposal.validation.valid ? "已通过校验" : "仍有校验问题"}
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
                  应用此补丁
                </button>
              </div>
            ) : null}
          </article>
        </section>

        <aside className="story-editor-inspector">
          <section className="story-editor-card">
            <h2>图与端口诊断</h2>
            <GraphCanvas graph={graph} />
            <h3>源码映射</h3>
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
            <h2>校验问题</h2>
            <Diagnostics validation={validation} />
          </section>
          {pathPreview ? (
            <section className="story-editor-card">
              <h2>测试分支</h2>
              <p>
                <code>{pathPreview.branchId}</code>
              </p>
              <p>最终节点：{String(pathPreview.finalState.currentNodeId || "-")}</p>
              <ol>
                {pathPreview.snapshots.map((snapshot) => (
                  <li key={snapshot.step}>
                    步骤 {snapshot.step} · {String(snapshot.action.type || "start")}
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

function GraphCanvas({ graph }: { graph: StoryGraphProjection }) {
  const nodes = useMemo(() => [...graph.narrative.nodes, ...graph.rules.nodes], [graph]);
  const edges = useMemo(
    () => [
      ...graph.narrative.edges.map((edge) => `${edge.from} → ${edge.to} · ${edge.label}`),
      ...graph.rules.edges.map((edge) => `${edge.from}.${edge.fromPort} → ${edge.to}.${edge.toPort}`),
    ],
    [graph],
  );
  const width = Math.max(600, ...nodes.map((node) => node.x + 220));
  const height = Math.max(260, ...nodes.map((node) => node.y + 100));
  return (
    <div className="story-editor-graph-scroll">
      <div className="story-editor-graph" style={{ height, width }}>
        {nodes.map((node) => (
          <div
            className="story-editor-graph-node"
            key={`${node.type}-${node.id}-${node.x}`}
            style={{ left: node.x, top: node.y }}
          >
            <strong>{node.title}</strong>
            <small>{node.type}</small>
          </div>
        ))}
        {edges.length ? (
          <ul className="story-editor-graph-edges" aria-label="图关系">
            {edges.map((edge) => (
              <li key={edge}>{edge}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

function Diagnostics({ validation }: { validation: StoryGenerationValidation | null }) {
  if (!validation) return <p>正在读取校验结果…</p>;
  if (!validation.issues.length)
    return <p className="story-editor-valid">Schema、引用、路径、演员表与秘密隔离均已通过。</p>;
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
