import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  cancelStoryGeneration,
  importGeneratedStoryProject,
  regenerateStoryGeneration,
  resumeStoryGeneration,
  startStoryGeneration,
} from "../../entities/story/repository";
import type { StoryGenerationStage, StoryGenerationTask } from "../../entities/story/types";
import type { TaskSnapshot } from "../../shared/platform/types";
import "./StoryGeneratorPage.css";

const stages: { id: StoryGenerationStage; label: string }[] = [
  { id: "requirements", label: "需求与假设" },
  { id: "bible", label: "故事圣经" },
  { id: "characters", label: "人物职责" },
  { id: "state", label: "状态与信号" },
  { id: "narrative", label: "剧情图" },
  { id: "logic", label: "逻辑图" },
  { id: "resources", label: "资源绑定" },
];

function taskFromUpdate(update: TaskSnapshot<StoryGenerationTask>) {
  return update.generationTask ?? update.result ?? null;
}

export function StoryGeneratorPage() {
  const navigate = useNavigate();
  const [synopsis, setSynopsis] = useState("");
  const [task, setTask] = useState<StoryGenerationTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [regenerationStage, setRegenerationStage] = useState<StoryGenerationStage>("narrative");
  const completed = useMemo(() => new Set(task?.completedStages ?? []), [task?.completedStages]);

  const track = (update: TaskSnapshot<StoryGenerationTask>) => {
    const next = taskFromUpdate(update);
    if (next) setTask(next);
  };

  const run = async (operation: () => Promise<StoryGenerationTask>) => {
    setBusy(true);
    setError("");
    try {
      setTask(await operation());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const start = () =>
    run(() =>
      startStoryGeneration(
        { synopsis, options: { controlMode: "deterministic", targetLength: "short" } },
        { onTaskUpdate: track },
      ),
    );
  const resume = () => task && run(() => resumeStoryGeneration(task.id, { onTaskUpdate: track }));
  const regenerate = () =>
    task && run(() => regenerateStoryGeneration(task.id, regenerationStage, { onTaskUpdate: track }));
  const cancel = async () => {
    if (!task) return;
    try {
      setTask(await cancelStoryGeneration(task.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };
  const openEditor = async () => {
    if (!task) return;
    setBusy(true);
    setError("");
    try {
      const project = await importGeneratedStoryProject(task.id);
      navigate(`/settings/stories/${project.manifest.id}/edit`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="story-generator-page">
      <header className="story-generator-header">
        <div>
          <p className="story-generator-eyebrow">AI STORY COMPILER</p>
          <h1>从剧情梗概生成可运行剧本</h1>
          <p>LLM 负责分阶段创作；Schema、引用、路径、演员表与秘密隔离由确定性编译器裁决。</p>
        </div>
      </header>

      <section className="story-generator-card" aria-labelledby="story-synopsis-title">
        <h2 id="story-synopsis-title">剧情梗概</h2>
        <textarea
          aria-label="剧情梗概"
          disabled={busy}
          maxLength={20000}
          onChange={(event) => setSynopsis(event.target.value)}
          placeholder="写下人物、核心冲突、希望保留的秘密与结局方向……"
          rows={8}
          value={synopsis}
        />
        <div className="story-generator-actions">
          <button disabled={busy || !synopsis.trim()} onClick={start} type="button">
            {busy ? "生成中…" : "开始生成"}
          </button>
          {task?.status === "failed" || task?.status === "cancelled" ? (
            <button disabled={busy} onClick={resume} type="button">
              从断点继续
            </button>
          ) : null}
          {task?.status === "running" ? (
            <button className="secondary" onClick={cancel} type="button">
              取消
            </button>
          ) : null}
        </div>
        {error ? (
          <p className="story-generator-error" role="alert">
            {error}
          </p>
        ) : null}
      </section>

      {task ? (
        <>
          <section className="story-generator-card" aria-labelledby="story-progress-title">
            <div className="story-generator-section-heading">
              <div>
                <h2 id="story-progress-title">生成进度</h2>
                <p>
                  状态：{task.status} · 当前阶段：{task.currentStage}
                </p>
              </div>
              <code>{task.id}</code>
            </div>
            <ol className="story-generator-stages">
              {stages.map((stage) => (
                <li
                  className={completed.has(stage.id) ? "completed" : task.currentStage === stage.id ? "active" : ""}
                  key={stage.id}
                >
                  <span aria-hidden>{completed.has(stage.id) ? "✓" : "·"}</span>
                  {stage.label}
                </li>
              ))}
            </ol>
          </section>

          <section className="story-generator-grid">
            <article className="story-generator-card">
              <h2>生成假设</h2>
              {task.assumptions.length ? (
                <ul>
                  {task.assumptions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p>需求阶段完成后显示。</p>
              )}
            </article>
            <article className="story-generator-card">
              <h2>校验摘要</h2>
              {task.validation ? (
                <>
                  <p className={task.validation.valid ? "story-generator-pass" : "story-generator-error"}>
                    {task.validation.valid ? "已通过确定性校验" : "仍有阻断问题"}
                  </p>
                  <dl className="story-generator-metrics">
                    <div>
                      <dt>结局覆盖</dt>
                      <dd>{Math.round(task.validation.endingCoverage * 100)}%</dd>
                    </div>
                    <div>
                      <dt>路径状态</dt>
                      <dd>{task.validation.exploredStates}</dd>
                    </div>
                    <div>
                      <dt>演员表失败</dt>
                      <dd>{task.validation.castFailureNodeIds.length}</dd>
                    </div>
                    <div>
                      <dt>估算 Tokens</dt>
                      <dd>{task.cost.estimatedTokens}</dd>
                    </div>
                  </dl>
                  {task.validation.issues.length ? (
                    <ul>
                      {task.validation.issues.map((issue) => (
                        <li key={`${issue.code}-${issue.path}`}>
                          {issue.code}: {issue.message}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : (
                <p>剧情图、逻辑图与资源绑定完成后运行。</p>
              )}
            </article>
          </section>

          {task.status === "succeeded" ? (
            <section className="story-generator-card story-generator-regenerate">
              <div>
                <h2>局部重新生成</h2>
                <p>所选阶段之后的产物会失效，之前的稳定产物保留。</p>
              </div>
              <select
                aria-label="重新生成阶段"
                onChange={(event) => setRegenerationStage(event.target.value as StoryGenerationStage)}
                value={regenerationStage}
              >
                {stages.map((stage) => (
                  <option key={stage.id} value={stage.id}>
                    {stage.label}
                  </option>
                ))}
              </select>
              <button disabled={busy} onClick={regenerate} type="button">
                重新生成
              </button>
              <button disabled={busy} onClick={openEditor} type="button">
                打开编辑器
              </button>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
