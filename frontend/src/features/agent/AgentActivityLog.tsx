import { useEffect, useState } from "react";
import { Check, CircleAlert, LoaderCircle, Wrench } from "lucide-react";
import { isTerminal, type AgentActivityEntry, type AgentTranscript } from "../../entities/agent/events";
import type { AgentTask } from "../../shared/platform/agentTypes";
import { useI18n, type MessageKey } from "../../shared/i18n";

const labels: Record<string, MessageKey> = {
  starting: "agent.activity.starting",
  thinking: "agent.thinking",
  responding: "agent.activity.responding",
  retrying: "agent.activity.retrying",
  compacting: "agent.activity.compacting",
  read: "agent.activity.read",
  write: "agent.activity.write",
  edit: "agent.activity.edit",
  bash: "agent.activity.command",
  powershell: "agent.activity.command",
  grep: "agent.activity.search",
  find: "agent.activity.find",
  ls: "agent.activity.listFiles",
  "characters.list": "agent.activity.characterNames",
  "characters.get": "agent.activity.character",
  "characters.save": "agent.activity.saveCharacter",
  "plugins.list": "agent.activity.plugins",
  "plugins.registry": "agent.activity.registry",
  "plugins.inspect": "agent.activity.plugin",
  "plugins.install": "agent.activity.installPlugin",
  "plugins.tools": "agent.activity.pluginTools",
  playwright_search_web: "agent.activity.webSearch",
  playwright_navigate: "agent.activity.webNavigate",
  playwright_get_text: "agent.activity.webRead",
  "app.config": "agent.activity.config",
  "logs.read": "agent.activity.logs",
};

function statusFor(activity: AgentActivityEntry, task: AgentTask) {
  if (activity.status !== "running" || !isTerminal(task.status)) return activity.status;
  return task.status === "cancelled" ? "cancelled" : "interrupted";
}

export function AgentActivityLog({
  task,
  transcript,
  enabled,
}: {
  task: AgentTask;
  transcript?: AgentTranscript;
  enabled: boolean;
}) {
  const { t } = useI18n();
  const [now, setNow] = useState(Date.now);
  const terminal = isTerminal(task.status);
  useEffect(() => {
    if (!enabled || terminal) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [enabled, terminal]);
  const activities = transcript?.activities ?? [];
  const current = activities
    .filter((activity) => activity.status === "running")
    .sort((a, b) => b.eventSeq - a.eventSeq)[0];
  const description = (activity: AgentActivityEntry) => {
    const path = activity.target.replace(/\\/g, "/");
    const skill = activity.name === "read" ? /\/skills\/([^/]+)\/SKILL\.md$/.exec(path)?.[1] : null;
    return {
      label: t(skill ? "agent.activity.skill" : (labels[activity.name] ?? "agent.activity.tool")),
      target:
        skill ??
        (labels[activity.name] ? activity.target : `${activity.name}${activity.target ? ` · ${activity.target}` : ""}`),
    };
  };
  const elapsed = (activity: AgentActivityEntry) => {
    const end =
      activity.status === "running" ? (terminal ? Date.parse(task.updatedAt) : now) : Date.parse(activity.updatedAt);
    const seconds = Math.max(0, Math.floor((end - Date.parse(activity.startedAt)) / 1000));
    return t("agent.activity.seconds", { count: Number.isFinite(seconds) ? seconds : 0 });
  };
  const title =
    task.status === "waiting_input" || task.status === "cancelling" || task.status === "queued"
      ? t(`agent.status.${task.status}` as MessageKey)
      : current
        ? description(current).label
        : t("agent.thinking");
  return (
    <section className="agent-activity" aria-label={t("agent.activity.history")}>
      {!terminal ? (
        <div className="agent-activity__current" role="status">
          <LoaderCircle aria-hidden className="agent-activity__spinner" />
          <div>
            <strong>{title}</strong>
            {current && task.status === "running" ? (
              <span className="agent-activity__target">{description(current).target}</span>
            ) : null}
          </div>
          {current ? <small>{elapsed(current)}</small> : null}
        </div>
      ) : null}
      {activities.length ? (
        <details className="agent-activity__history" open={!terminal}>
          <summary>{t("agent.activity.steps", { count: activities.length })}</summary>
          <ol>
            {activities.map((activity) => {
              const status = statusFor(activity, task);
              const Icon = status === "running" ? LoaderCircle : status === "succeeded" ? Check : CircleAlert;
              const { label, target } = description(activity);
              const tool = transcript?.tools.find((item) => item.callId === activity.hostCallId);
              return (
                <li key={activity.activityId} className={`agent-activity__step agent-activity__step--${status}`}>
                  <Icon aria-hidden className={status === "running" ? "agent-activity__spinner" : undefined} />
                  <div className="agent-activity__body">
                    <strong>{label}</strong>
                    {target ? <span className="agent-activity__target">{target}</span> : null}
                    <small>
                      {t(`agent.status.${status}` as MessageKey)} · {elapsed(activity)}
                    </small>
                    {tool ? (
                      <details className="agent-tool">
                        <summary>
                          <Wrench aria-hidden />
                          {t("agent.activity.details")}
                        </summary>
                        <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
                        {tool.result ? (
                          <pre>
                            {tool.result.ok ? JSON.stringify(tool.result.data, null, 2) : tool.result.error?.message}
                          </pre>
                        ) : null}
                      </details>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}
    </section>
  );
}
