import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, PanelRightClose } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  readStoryDocument,
  saveStoryDocument,
  storyLibraryQueryKey,
  suggestStoryGraph,
} from "../../../entities/story/repository";
import { useI18n } from "../../../shared/i18n";
import { Button, Dialog, Select, TextArea, TextInput } from "../../../shared/ui";
import type { StoryDocument, StorySuggestion } from "../../../shared/platform/storyEditorTypes";
import type { StoryGraph } from "../../../shared/platform/storyPreviewTypes";
import { StoryCanvas } from "./StoryCanvas";
import { StoryLaunchButton } from "../components/StoryLaunchButton";
import { StoryNodeForm } from "./StoryNodeForm";
import { StoryProposal } from "./StoryProposal";
import "./StoryEditor.css";

type Draft = Pick<StoryDocument, "title" | "graph">;
const draftKey = (doc: StoryDocument) => `story-editor.v1:${doc.storyPath}:${doc.sourceHash}`;
function restore(doc: StoryDocument): Draft {
  try {
    const saved = JSON.parse(sessionStorage.getItem(draftKey(doc)) || "null");
    if (
      typeof saved?.title === "string" &&
      Array.isArray(saved?.graph?.nodes) &&
      saved.graph.nodes.length &&
      typeof saved.graph.startNodeId === "string"
    )
      return saved;
  } catch {
    /* A broken browser draft must not prevent opening the source. */
  }
  return { title: doc.title, graph: doc.graph };
}

export function StoryEditor({
  storyPath,
  onClose,
  onPendingChange,
}: {
  storyPath: string;
  onClose?: () => void;
  onPendingChange?: (pending: boolean) => void;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const titleId = useId();
  const reportPending = useCallback(
    (value: boolean) => {
      setBusy(value);
      onPendingChange?.(value);
    },
    [onPendingChange],
  );
  const query = useQuery({
    queryKey: ["story-document", storyPath],
    queryFn: () => readStoryDocument(storyPath),
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
  return createPortal(
    <section className="page story-studio" aria-labelledby={titleId}>
      <header className="page__header">
        <div className="story-studio__heading">
          <Button
            variant="ghost"
            icon={<ArrowLeft aria-hidden size={18} />}
            disabled={busy || !onClose}
            onClick={onClose}
          >
            {t("story.editor.back")}
          </Button>
          <h1 className="page__title" id={titleId}>
            {t("story.editor.title")}
          </h1>
        </div>
      </header>
      <div className="story-editor">
        {query.isPending && <p role="status">{t("common.loading")}</p>}
        {query.isError && (
          <>
            <p role="alert">{query.error.message}</p>
            <Button onClick={() => void query.refetch()}>{t("common.refresh")}</Button>
          </>
        )}
        {query.data && (
          <EditorDraft
            key={`${query.data.storyPath}:${query.data.sourceHash}`}
            initial={query.data}
            onPendingChange={reportPending}
          />
        )}
      </div>
    </section>,
    document.querySelector(".desktop-frame__content") ?? document.body,
  );
}

function EditorDraft({
  initial,
  onPendingChange,
}: {
  initial: StoryDocument;
  onPendingChange?: (pending: boolean) => void;
}) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [document, setDocument] = useState(initial);
  const [draft, setDraft] = useState<Draft>(() => restore(initial));
  const [history, setHistory] = useState<Draft[]>([]);
  const [selectedId, setSelectedId] = useState(draft.graph.startNodeId);
  const [scope, setScope] = useState<"node" | "graph">("node");
  const [instructions, setInstructions] = useState("");
  const [proposal, setProposal] = useState<StorySuggestion | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [panel, setPanel] = useState<"node" | "ai" | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    onPendingChange?.(pending);
    return () => onPendingChange?.(false);
  }, [pending, onPendingChange]);
  useEffect(() => {
    try {
      sessionStorage.setItem(draftKey(document), JSON.stringify(draft));
    } catch {
      /* Editing still works if storage is full. */
    }
  }, [document, draft]);
  const dirty = JSON.stringify(draft) !== JSON.stringify({ title: document.title, graph: document.graph });
  const selected = draft.graph.nodes.find((node) => node.id === selectedId) ?? draft.graph.nodes[0];
  const locked = pending || Boolean(proposal);
  const change = (next: Draft) => {
    if (running.current) return;
    setHistory((items) => [...items.slice(-29), draft]);
    setDraft(next);
    setSaved(false);
    setError("");
  };
  const changeGraph = (graph: StoryGraph) => change({ ...draft, graph });
  const run = async (action: "save" | "suggest") => {
    if (running.current) return;
    running.current = true;
    setPending(true);
    setError("");
    setSaved(false);
    const input = { storyPath: document.storyPath, sourceHash: document.sourceHash, ...draft };
    try {
      if (action === "suggest") {
        const result = await suggestStoryGraph({
          ...input,
          scope,
          nodeId: scope === "node" ? selected.id : undefined,
          instructions,
        });
        if (mounted.current) setProposal(result);
      } else {
        const result = await saveStoryDocument(input);
        if (mounted.current) {
          try {
            sessionStorage.removeItem(draftKey(document));
            const layout = sessionStorage.getItem(`story-canvas:${document.storyPath}`);
            if (layout) sessionStorage.setItem(`story-canvas:${result.storyPath}`, layout);
          } catch {
            /* Optional draft cache. */
          }
          setDocument(result);
          setDraft({ title: result.title, graph: result.graph });
          setHistory([]);
          setSaved(true);
        }
        void client.invalidateQueries({ queryKey: storyLibraryQueryKey });
      }
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      running.current = false;
      if (mounted.current) setPending(false);
    }
  };
  return (
    <>
      <header className="story-editor__toolbar">
        <label className="story-editor__name">
          <span>{t("story.editor.storyTitle")}</span>
          <TextInput
            disabled={locked}
            value={draft.title}
            maxLength={200}
            onChange={(e) => change({ ...draft, title: e.target.value })}
          />
        </label>
        <div className="story-editor__actions">
          <Button
            disabled={locked || draft.graph.nodes.length >= 100}
            onClick={() => {
              let index = 1;
              while (draft.graph.nodes.some((node) => node.id === `node-${index}`)) index++;
              const id = `node-${index}`;
              changeGraph({
                ...draft.graph,
                nodes: [
                  ...draft.graph.nodes,
                  { id, title: t("story.editor.newNode"), type: "free_chat_node", instruction: "", transitions: [] },
                ],
              });
              setSelectedId(id);
              setPanel("node");
            }}
          >
            {t("story.editor.addNode")}
          </Button>
          <Button
            disabled={locked || !history.length}
            onClick={() => {
              setDraft(history[history.length - 1]);
              setHistory(history.slice(0, -1));
              setError("");
              setSaved(false);
            }}
          >
            {t("story.editor.undo")}
          </Button>
          <Button aria-pressed={panel === "ai"} onClick={() => setPanel(panel === "ai" ? null : "ai")}>
            {t("story.editor.ai")}
          </Button>
          <label className="story-editor__start">
            <span>{t("story.editor.start")}</span>
            <Select
              aria-label={t("story.editor.start")}
              disabled={locked}
              value={draft.graph.startNodeId}
              onChange={(e) => changeGraph({ ...draft.graph, startNodeId: e.target.value })}
            >
              {draft.graph.nodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.title || node.id}
                </option>
              ))}
            </Select>
          </label>
        </div>
      </header>
      <div className={`story-editor__workspace ${panel ? "has-panel" : ""}`}>
        <StoryCanvas
          graph={draft.graph}
          selectedId={selected?.id}
          disabled={locked}
          storageKey={`story-canvas:${document.storyPath}`}
          onSelect={(id, inspect = true) => {
            setSelectedId(id);
            if (inspect) setPanel("node");
          }}
          onConnect={(from, to) => {
            changeGraph({
              ...draft.graph,
              nodes: draft.graph.nodes.map((node) =>
                node.id === from ? { ...node, transitions: [...(node.transitions ?? []), { to, when: "" }] } : node,
              ),
            });
            setSelectedId(from);
            setPanel("node");
          }}
        />
        <aside className="story-editor__inspector" hidden={!panel}>
          <header className="story-editor__panel-header">
            <h2>{t(panel === "ai" ? "story.editor.ai" : "story.editor.node")}</h2>
            <Button aria-label={t("story.canvas.hidePanel")} onClick={() => setPanel(null)}>
              <PanelRightClose aria-hidden size={16} />
            </Button>
          </header>
          <div className="story-editor__panel-scroll" hidden={panel !== "node"}>
            {selected && (
              <section className="section">
                <StoryNodeForm
                  graph={draft.graph}
                  node={selected}
                  disabled={locked}
                  onChange={(node) =>
                    changeGraph({
                      ...draft.graph,
                      nodes: draft.graph.nodes.map((item) => (item.id === node.id ? node : item)),
                    })
                  }
                />
                <Button
                  disabled={locked || draft.graph.nodes.length === 1}
                  onClick={() => {
                    const nodes = draft.graph.nodes
                      .filter((node) => node.id !== selected.id)
                      .map((node) => ({
                        ...node,
                        transitions: node.transitions?.filter((edge) => edge.to !== selected.id),
                        defaultTo: node.defaultTo === selected.id ? undefined : node.defaultTo,
                      }));
                    changeGraph({
                      startNodeId: draft.graph.startNodeId === selected.id ? nodes[0].id : draft.graph.startNodeId,
                      nodes,
                    });
                    setSelectedId(nodes[0].id);
                  }}
                >
                  {t("story.editor.deleteNode")}
                </Button>
              </section>
            )}
          </div>
          <section className="story-editor__ai story-editor__panel-scroll" hidden={panel !== "ai"}>
            {document.authoringBrief && (
              <details>
                <summary>{t("story.editor.brief")}</summary>
                <p className="story-editor__text">{document.authoringBrief}</p>
              </details>
            )}
            <p className="section__description">{t("story.editor.aiHint")}</p>
            <label>
              {t("story.editor.scope")}
              <Select
                aria-label={t("story.editor.scope")}
                disabled={locked}
                value={scope}
                onChange={(e) => setScope(e.target.value as "node" | "graph")}
              >
                <option value="node">{t("story.editor.scopeNode", { title: selected?.title || "" })}</option>
                <option value="graph">{t("story.editor.scopeGraph")}</option>
              </Select>
            </label>
            <label>
              {t("story.editor.request")}
              <TextArea
                disabled={locked}
                rows={3}
                maxLength={20000}
                value={instructions}
                placeholder={t("story.editor.requestPlaceholder")}
                onChange={(e) => setInstructions(e.target.value)}
              />
            </label>
            <Button disabled={locked || !instructions.trim()} onClick={() => void run("suggest")}>
              {t("story.editor.suggest")}
            </Button>
          </section>
        </aside>
      </div>
      {proposal && (
        <Dialog
          open
          title={t("story.editor.proposal")}
          className="story-editor__review"
          onClose={() => setProposal(null)}
          closeLabel={t("common.close")}
        >
          <StoryProposal
            before={draft.graph}
            proposal={proposal}
            onApply={() => {
              changeGraph(proposal.graph);
              setProposal(null);
              setPanel("node");
            }}
            onDiscard={() => setProposal(null)}
          />
        </Dialog>
      )}
      <footer className="story-editor__statusbar">
        <span className="story-editor__version" title={t("story.editor.versionHint")}>
          {t("story.editor.version", { version: document.version })}
          {dirty ? " · ●" : ""}
        </span>
        {pending && <p role="status">{t("story.editor.working")}</p>}
        {error && (
          <p role="alert" className="story-generator-error story-editor__text">
            {error}
          </p>
        )}
        <div className="story-editor__actions">
          <Button variant="primary" disabled={locked || !dirty || !draft.title.trim()} onClick={() => void run("save")}>
            {t("story.editor.save")}
          </Button>
          {saved && (
            <>
              <p role="status">{t("story.editor.saved")}</p>
              <StoryLaunchButton storyPath={document.storyPath} label={t("story.editor.play")} />
            </>
          )}
        </div>
      </footer>
    </>
  );
}
