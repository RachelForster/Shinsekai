import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Plus, Send, Square, Wrench, X } from "lucide-react";
import { Link } from "react-router-dom";

import { agentApi, agentQueryKey, listAgentSessions } from "../../entities/agent/repository";
import { isTerminal, type AgentTranscript } from "../../entities/agent/events";
import type { AgentArtifact, AgentInputRequest, AgentSession, AgentTask } from "../../shared/platform/agentTypes";
import { useI18n } from "../../shared/i18n";
import type { MessageKey } from "../../shared/i18n";
import { Button, Dialog, QueryErrorState } from "../../shared/ui";
import { useAgentConversation } from "./useAgentConversation";
import "./agent.css";

function MessageText({ text }: { text: string }) {
  const blocks = text.split(/```[^\n]*\n([\s\S]*?)(?:```|$)/g);
  return (
    <div className="agent-message-text">
      {blocks.map((block, index) =>
        index % 2 ? (
          <pre key={index}>
            <code>{block}</code>
          </pre>
        ) : (
          <span key={index}>{block}</span>
        ),
      )}
    </div>
  );
}

function InputPrompt({
  taskId,
  request,
  onAnswered,
}: {
  taskId: string;
  request: AgentInputRequest;
  onAnswered: () => void;
}) {
  const { t } = useI18n();
  const [answer, setAnswer] = useState("");
  const expired = !!request.expiresAt && new Date(request.expiresAt).getTime() <= Date.now();
  const mutation = useMutation({
    mutationFn: (value: unknown) => agentApi().respondInput(taskId, { inputRequestId: request.inputRequestId, value }),
    onSuccess: onAnswered,
  });
  return (
    <section className="agent-input-prompt" aria-label={t("agent.inputNeeded")}>
      <p>{request.question}</p>
      {request.kind === "confirmation" ? (
        <div className="agent-actions">
          <Button disabled={expired || mutation.isPending} onClick={() => mutation.mutate(true)} variant="primary">
            {t("agent.confirm")}
          </Button>
          <Button disabled={expired || mutation.isPending} onClick={() => mutation.mutate(false)}>
            {t("agent.deny")}
          </Button>
        </div>
      ) : request.options?.length ? (
        <div className="agent-actions">
          {request.options.map((option) => (
            <Button
              disabled={expired || mutation.isPending}
              key={option.value}
              onClick={() => mutation.mutate(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (answer.trim()) mutation.mutate(answer);
          }}
        >
          <textarea
            aria-label={request.question}
            disabled={expired || mutation.isPending}
            onChange={(event) => setAnswer(event.target.value)}
            rows={2}
            value={answer}
          />
          <Button disabled={expired || !answer.trim()} loading={mutation.isPending} type="submit">
            {t("agent.reply")}
          </Button>
        </form>
      )}
      {expired ? <p>{t("agent.inputExpired")}</p> : null}
      {mutation.error ? (
        <p className="agent-error" role="alert">
          {mutation.error.message}
        </p>
      ) : null}
    </section>
  );
}

function TaskTurn({
  task,
  transcript,
  onCancel,
  cancelling,
  onAnswered,
  onArtifact,
}: {
  task: AgentTask;
  transcript?: AgentTranscript;
  onCancel: () => void;
  cancelling: boolean;
  onAnswered: () => void;
  onArtifact: (artifact: AgentArtifact) => void;
}) {
  const { t } = useI18n();
  const messages = transcript?.messages ?? [];
  return (
    <article className="agent-turn">
      <div className="agent-message agent-message--user">
        <span className="agent-message__role">{t("agent.you")}</span>
        <MessageText text={task.input.text} />
      </div>
      <div className="agent-message agent-message--assistant">
        <div className="agent-message__header">
          <span className="agent-message__role">
            <Bot aria-hidden />
            {t("nav.assistant")}
          </span>
          <span className={`agent-task-status agent-task-status--${task.status}`}>
            {t(`agent.status.${task.status}` as MessageKey)}
          </span>
        </div>
        {messages.map((message) => (
          <MessageText key={message.id} text={message.text} />
        ))}
        {!messages.length && task.result?.summary ? <MessageText text={task.result.summary} /> : null}
        {!messages.length && !isTerminal(task.status) ? (
          <span className="agent-thinking">
            {t(task.status === "queued" ? "agent.status.queued" : "agent.thinking")}
          </span>
        ) : null}
        {transcript?.tools.map((tool) => (
          <details className="agent-tool" key={tool.callId}>
            <summary>
              <Wrench aria-hidden />
              {tool.name}
              <span>
                {t(!tool.result ? "agent.toolRunning" : tool.result.ok ? "agent.toolDone" : "agent.toolFailed")}
              </span>
            </summary>
            <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
            {tool.result ? (
              <pre>{tool.result.ok ? JSON.stringify(tool.result.data, null, 2) : tool.result.error?.message}</pre>
            ) : null}
          </details>
        ))}
        {task.status === "waiting_input" && transcript?.input ? (
          <InputPrompt
            key={transcript.input.inputRequestId}
            onAnswered={onAnswered}
            request={transcript.input}
            taskId={task.taskId}
          />
        ) : null}
        {task.error ? (
          <p className="agent-error" role="alert">
            {task.error.message} <span className="agent-error__code">{task.error.code}</span>
          </p>
        ) : null}
        {task.result?.warnings.map((warning, index) => (
          <p className="agent-warning" key={index}>
            {warning}
          </p>
        ))}
        {task.result?.effects.map((effect) => (
          <p className="agent-effect" key={effect.callId}>
            {effect.toolName}: {effect.state} {effect.description}
          </p>
        ))}
        {task.result?.artifacts.map((artifact) => (
          <Button key={artifact.artifactId} onClick={() => onArtifact(artifact)}>
            {artifact.title}
          </Button>
        ))}
        <div className="agent-message__footer">
          {transcript?.usage?.totalTokens != null ? (
            <small>{t("agent.tokens", { count: transcript.usage.totalTokens })}</small>
          ) : null}
          {!isTerminal(task.status) ? (
            <Button
              disabled={task.status === "cancelling"}
              icon={<Square aria-hidden />}
              loading={cancelling}
              onClick={onCancel}
              variant="ghost"
            >
              {t("agent.stop")}
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function AgentPanel({ enabled = true, onNavigate }: { enabled?: boolean; onNavigate?: () => void }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [artifact, setArtifact] = useState<{ title: string; text: string } | null>(null);
  const requestIds = useRef(new Map<string, { text: string; id: string }>());
  const scroll = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const runtime = useQuery({
    queryKey: [...agentQueryKey, "runtime"],
    queryFn: ({ signal }) => agentApi().runtime(signal),
    enabled,
    refetchInterval: enabled ? 1500 : false,
    retry: false,
  });
  const sessions = useQuery({
    queryKey: [...agentQueryKey, "sessions"],
    queryFn: ({ signal }) => listAgentSessions(signal),
    enabled,
    refetchInterval: enabled ? 3000 : false,
    retry: false,
  });
  const { tasks, transcript } = useAgentConversation(selected, enabled);
  const session = sessions.data?.find((item) => item.sessionId === selected);
  const draft = drafts[selected] ?? "";
  const pending = tasks.data?.some((task) => !isTerminal(task.status)) ?? false;
  const refresh = () => queryClient.invalidateQueries({ queryKey: agentQueryKey });
  const create = useMutation({
    mutationFn: () => agentApi().createSession(),
    onSuccess: async (value) => {
      queryClient.setQueryData<AgentSession[]>([...agentQueryKey, "sessions"], (current) => [
        ...(current ?? []).filter((item) => item.sessionId !== value.sessionId),
        value,
      ]);
      setSelected(value.sessionId);
      await queryClient.invalidateQueries({ queryKey: [...agentQueryKey, "sessions"] });
      composer.current?.focus();
    },
  });
  const close = useMutation({
    mutationFn: (sessionId: string) => agentApi().closeSession(sessionId),
    onSuccess: async (_, sessionId) => {
      if (selected === sessionId) setSelected("");
      await queryClient.invalidateQueries({ queryKey: [...agentQueryKey, "sessions"] });
    },
  });
  const prepare = useMutation({ mutationFn: () => agentApi().start(), onSettled: refresh });
  const resume = useMutation({ mutationFn: () => agentApi().resumeQueue(), onSettled: refresh });
  const cancel = useMutation({ mutationFn: (taskId: string) => agentApi().cancelTask(taskId), onSettled: refresh });
  const readArtifact = useMutation({
    mutationFn: (value: AgentArtifact) => agentApi().readArtifact(value.artifactId, value.revision),
    onSuccess: (value) => setArtifact({ title: value.artifact.title, text: value.text ?? "" }),
  });
  const send = useMutation({
    mutationFn: (value: { sessionId: string; requestId: string; text: string }) =>
      agentApi().submitTask(value.sessionId, { requestId: value.requestId, text: value.text }),
    onSuccess: async (_, value) => {
      requestIds.current.delete(value.sessionId);
      setDrafts((current) =>
        current[value.sessionId]?.trim() === value.text ? { ...current, [value.sessionId]: "" } : current,
      );
      stickToBottom.current = true;
      await refresh();
    },
  });
  useEffect(() => {
    if (sessions.data && !sessions.data.some((item) => item.sessionId === selected))
      setSelected(sessions.data[0]?.sessionId ?? "");
  }, [selected, sessions.data]);
  useEffect(() => {
    stickToBottom.current = true;
  }, [selected]);
  const scrollVersion = tasks.data
    ?.map((task) => `${task.taskId}:${transcript.data?.[task.taskId]?.nextSeq ?? 0}`)
    .join("|");
  useEffect(() => {
    if (stickToBottom.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [selected, scrollVersion]);
  const ready = runtime.data?.status === "ready" && !runtime.data.configurationChanged;
  const compatible = !!session && session.modelRef === runtime.data?.modelRef;
  const canSend = ready && compatible && !runtime.data?.queuePaused && !pending && !send.isPending && !!draft.trim();
  const submit = () => {
    if (!canSend) return;
    const text = draft.trim();
    let request = requestIds.current.get(selected);
    if (!request || request.text !== text) {
      request = { text, id: crypto.randomUUID() };
      requestIds.current.set(selected, request);
    }
    send.mutate({ sessionId: selected, text, requestId: request.id });
  };
  const error =
    create.error ?? close.error ?? prepare.error ?? resume.error ?? cancel.error ?? readArtifact.error ?? send.error;
  const phaseKey = `agent.phase.${runtime.data?.phase}` as MessageKey;
  return (
    <div className="agent-panel">
      <div className="agent-panel__toolbar">
        <p>{t("agent.subtitle")}</p>
        <div className="agent-actions">
          <Link onClick={onNavigate} to="/settings/api">
            {t("nav.api")}
          </Link>
          <Link onClick={onNavigate} to="/settings/tools">
            {t("nav.tools")}
          </Link>
          <Button
            disabled={!ready}
            icon={<Plus aria-hidden />}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            {t("agent.newSession")}
          </Button>
        </div>
      </div>
      {runtime.error ? (
        <QueryErrorState
          error={runtime.error}
          onRetry={() => void runtime.refetch()}
          retryLabel={t("common.retry")}
          title={t("agent.loadFailed")}
        />
      ) : null}
      {runtime.data?.preview ? <p className="agent-notice">{t("agent.preview")}</p> : null}
      {runtime.data?.status === "preparing" ? (
        <div className="agent-notice" role="status">
          <span>
            {["configure", "verify", "download", "extract"].includes(runtime.data.phase)
              ? t(phaseKey)
              : t("agent.preparing")}
          </span>
          <progress aria-label={t("agent.preparing")} max={1} value={runtime.data.progress} />
        </div>
      ) : null}
      {runtime.data?.status === "error" || runtime.data?.status === "idle" ? (
        <div className="agent-notice">
          <p>{runtime.data.error?.message ?? t("agent.notReady")}</p>
          <Button loading={prepare.isPending} onClick={() => prepare.mutate()}>
            {t("agent.retryPrepare")}
          </Button>
        </div>
      ) : null}
      {runtime.data?.configurationChanged ? (
        <div className="agent-notice">
          <p>{t("agent.configurationChanged")}</p>
          <Button loading={prepare.isPending} onClick={() => prepare.mutate()}>
            {t("agent.applyConfiguration")}
          </Button>
        </div>
      ) : null}
      {runtime.data?.queuePaused ? (
        <div className="agent-notice">
          <p>{t("agent.queuePaused")}</p>
          <Button disabled={!ready} loading={resume.isPending} onClick={() => resume.mutate()}>
            {t("agent.resumeQueue")}
          </Button>
        </div>
      ) : null}
      {sessions.error ? (
        <QueryErrorState
          error={sessions.error}
          onRetry={() => void sessions.refetch()}
          retryLabel={t("common.retry")}
          title={t("agent.loadFailed")}
        />
      ) : null}
      <div className="agent-tabs" role="tablist" aria-label={t("agent.sessions")}>
        {sessions.data?.map((item, index) => {
          const name = t("agent.session", { number: index + 1 });
          return (
            <div
              className={`agent-tab${selected === item.sessionId ? " agent-tab--selected" : ""}`}
              key={item.sessionId}
            >
              <button
                aria-controls="agent-conversation"
                aria-selected={selected === item.sessionId}
                id={`agent-tab-${item.sessionId}`}
                onClick={() => setSelected(item.sessionId)}
                onKeyDown={(event) => {
                  const items = sessions.data ?? [];
                  const next =
                    event.key === "ArrowRight"
                      ? (index + 1) % items.length
                      : event.key === "ArrowLeft"
                        ? (index - 1 + items.length) % items.length
                        : event.key === "Home"
                          ? 0
                          : event.key === "End"
                            ? items.length - 1
                            : -1;
                  if (next >= 0) {
                    event.preventDefault();
                    setSelected(items[next].sessionId);
                    document.getElementById(`agent-tab-${items[next].sessionId}`)?.focus();
                  }
                }}
                role="tab"
                tabIndex={selected === item.sessionId ? 0 : -1}
                type="button"
              >
                {name}
              </button>
              <button
                aria-label={t("agent.closeSession", { name })}
                disabled={close.isPending || (selected === item.sessionId && pending)}
                onClick={() => close.mutate(item.sessionId)}
                type="button"
              >
                <X aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
      <section
        aria-labelledby={selected ? `agent-tab-${selected}` : undefined}
        className="agent-conversation"
        id="agent-conversation"
        role="tabpanel"
      >
        <div
          className="agent-history"
          onScroll={() => {
            if (scroll.current)
              stickToBottom.current =
                scroll.current.scrollHeight - scroll.current.scrollTop - scroll.current.clientHeight < 100;
          }}
          ref={scroll}
        >
          {!selected || !tasks.data?.length ? (
            <div className="agent-empty">
              <Bot aria-hidden />
              <h3>{t("agent.welcome")}</h3>
              <p>{t(selected ? "agent.emptySession" : "agent.empty")}</p>
            </div>
          ) : null}
          {tasks.error || transcript.error ? (
            <QueryErrorState
              error={tasks.error ?? transcript.error}
              onRetry={() => void refresh()}
              retryLabel={t("common.retry")}
              title={t("agent.loadFailed")}
            />
          ) : null}
          <div aria-live="polite" role="log" aria-label={t("agent.history")}>
            {tasks.data?.map((task) => (
              <TaskTurn
                cancelling={cancel.isPending && cancel.variables === task.taskId}
                key={task.taskId}
                onAnswered={() => void refresh()}
                onArtifact={(value) => readArtifact.mutate(value)}
                onCancel={() => cancel.mutate(task.taskId)}
                task={task}
                transcript={transcript.data?.[task.taskId]}
              />
            ))}
          </div>
        </div>
        {session && ready && !compatible ? <p className="agent-notice">{t("agent.sessionMismatch")}</p> : null}
        {error ? (
          <p className="agent-error agent-action-error" role="alert">
            {error.message}
          </p>
        ) : null}
        <form
          className="agent-composer"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <textarea
            aria-label={t("agent.message")}
            disabled={!session || send.isPending}
            maxLength={64000}
            onChange={(event) => setDrafts((current) => ({ ...current, [selected]: event.target.value }))}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={t("agent.placeholder")}
            ref={composer}
            rows={3}
            value={draft}
          />
          <div className="agent-composer__footer">
            <small>{t("agent.sendHint")}</small>
            <Button
              aria-label={t("agent.send")}
              disabled={!canSend}
              icon={<Send aria-hidden />}
              loading={send.isPending}
              type="submit"
              variant="primary"
            >
              {t("agent.send")}
            </Button>
          </div>
        </form>
      </section>
      <Dialog
        closeLabel={t("common.close")}
        onClose={() => setArtifact(null)}
        open={!!artifact}
        title={artifact?.title ?? ""}
      >
        <MessageText text={artifact?.text ?? ""} />
      </Dialog>
    </div>
  );
}
