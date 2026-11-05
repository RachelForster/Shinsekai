import { useEffect, useRef, useState } from "react";

import { spriteMouthRepository } from "../../entities/character/repository";
import type {
  Character,
  GeneratedSpriteMouth,
  MouthPose,
  SpriteMouthCorrection,
  SpriteMouthInput,
  SpriteMouthManual,
  SpriteMouthSetup,
  TaskSnapshot,
} from "../../shared/platform/types";

const MOUTH_SAVE_BATCH_SIZE = 12;

export const defaultMouthCorrection: SpriteMouthCorrection = { offsetX: 0, offsetY: 0, scale: 1, rotation: 0, gain: 1 };
export interface MouthCalibrationDraft {
  manual: SpriteMouthManual;
  manualEnabled: boolean;
  selectedFrames: Record<MouthPose, number>;
}
export interface MouthCandidate {
  path: string;
  result?: GeneratedSpriteMouth;
  error?: string;
  selected: boolean;
  saved?: boolean;
  correction: SpriteMouthCorrection;
  draft?: MouthCalibrationDraft;
  calibrationDirty?: boolean;
  applyFailed?: boolean;
}
type MouthOptions = Omit<SpriteMouthInput, "name" | "spritePath">;
type Busy = "generate" | "save" | "setup" | "remove";
interface MouthSave {
  path: string;
  taskId: string;
  correction: SpriteMouthCorrection;
}
type MouthJob = { name: string; path: string } & (
  | { kind: "generate" | "apply"; options: MouthOptions; saveAfter?: boolean }
  | { kind: "save"; item: MouthSave }
);

export function useSpriteMouths(
  character: Character,
  name: string,
  onSaved: (character: Character) => void,
  externalBusy = false,
) {
  const [items, setItems] = useState<MouthCandidate[]>([]);
  const [selection, setSelection] = useState<string[]>([]);
  const [setup, setSetup] = useState<SpriteMouthSetup | null>(null);
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [activePath, setActivePath] = useState("");
  const [pendingPaths, setPendingPaths] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [queue, setQueue] = useState({ current: 0, total: 0 });
  const [stopping, setStopping] = useState(false);
  const lock = useRef<Busy | null>(null);
  const jobs = useRef<MouthJob[]>([]);
  const runningJob = useRef<MouthJob>();
  const progress = useRef({ current: 0, total: 0 });
  const external = useRef(externalBusy);
  external.current = externalBusy;
  const latestItems = useRef(items);
  latestItems.current = items;
  const paths = new Set(character.sprites.map((sprite) => sprite.path));
  const catalog = JSON.stringify([name, [...paths].sort()]);
  const currentSource = useRef({ name, paths });
  currentSource.current = { name, paths };
  const previousName = useRef(name);
  const isCurrent = (job: MouthJob) =>
    job.name === currentSource.current.name && currentSource.current.paths.has(job.path);
  const message = (failure: unknown) => (failure instanceof Error ? failure.message : String(failure));
  const mutate = (change: (values: MouthCandidate[]) => MouthCandidate[]) =>
    setItems((values) => {
      const result = change(values);
      latestItems.current = result;
      return result;
    });
  const update = (path: string, patch: Partial<MouthCandidate>) =>
    mutate((values) => values.map((item) => (item.path === path ? { ...item, ...patch } : item)));
  const syncPending = () => setPendingPaths(jobs.current.map((job) => job.path));
  const persist = async (owner: string, snapshots: MouthSave[]) => {
    const saved = await spriteMouthRepository.save({
      name: owner,
      items: snapshots.map(({ taskId, correction }) => ({ taskId, correction })),
    });
    if (owner !== currentSource.current.name) return;
    onSaved(saved);
    mutate((values) =>
      values.map((item) =>
        !item.calibrationDirty &&
        snapshots.some(
          (snapshot) =>
            snapshot.path === item.path &&
            snapshot.taskId === item.result?.taskId &&
            snapshot.correction === item.correction,
        )
          ? { ...item, saved: true, selected: false }
          : item,
      ),
    );
  };

  useEffect(() => {
    const changedCharacter = previousName.current !== name;
    previousName.current = name;
    mutate((values) => (changedCharacter ? [] : values.filter((item) => paths.has(item.path))));
    setSelection((values) => (changedCharacter ? [] : values.filter((path) => paths.has(path))));
    const kept = jobs.current.filter(isCurrent);
    progress.current.total -= jobs.current.length - kept.length;
    jobs.current = kept;
    setQueue({ ...progress.current });
    syncPending();
  }, [catalog]);

  async function pump() {
    if (lock.current || external.current || !jobs.current.length) return;
    lock.current = "generate";
    setBusy("generate");
    setError("");
    try {
      while (jobs.current.length && !external.current) {
        const job = jobs.current.shift()!;
        syncPending();
        if (!isCurrent(job)) continue;
        runningJob.current = job;
        setActivePath(job.path);
        setBusy(job.kind === "save" ? "save" : "generate");
        setTask(null);
        progress.current.current += 1;
        setQueue({ ...progress.current });
        update(job.path, { error: undefined });
        let snapshot: MouthSave | undefined;
        try {
          if (job.kind === "save") {
            await persist(job.name, [job.item]);
            continue;
          }
          const reanalysis = job.kind === "apply";
          const result = await spriteMouthRepository.generate(
            { name: job.name, spritePath: job.path, ...job.options },
            { onTaskUpdate: setTask },
          );
          if (!isCurrent(job)) continue;
          const appliedCorrection = job.options.correction ?? result.correction ?? result.profile?.correction;
          mutate((values) =>
            values.map((item) => {
              if (item.path !== job.path) return item;
              const combined = reanalysis
                ? {
                    ...result,
                    frames: result.frames?.length ? result.frames : item.result?.frames,
                    speechVideo: item.result?.speechVideo || result.speechVideo,
                    speechFps: result.speechFps ?? item.result?.speechFps,
                    reference: result.reference || item.result?.reference,
                    selectedFrames: result.selectedFrames ?? job.options.selectedFrames ?? item.result?.selectedFrames,
                    manual:
                      result.manual !== undefined
                        ? result.manual
                        : job.options.manual === undefined
                          ? item.result?.manual
                          : job.options.manual,
                  }
                : result;
              const keepDraft = !reanalysis && Boolean(result.cached && item.calibrationDirty);
              const keepCorrection = Boolean(result.cached && item.result && !item.saved);
              return {
                ...item,
                result: combined,
                error: undefined,
                correction:
                  keepCorrection && !job.options.correction ? item.correction : (appliedCorrection ?? item.correction),
                draft: keepDraft || (!result.ready && reanalysis) ? item.draft : undefined,
                calibrationDirty: keepDraft || (!result.ready && reanalysis),
                applyFailed: !result.ready && reanalysis,
                selected: result.ready && (!result.cached || item.selected) && !keepDraft,
                saved: Boolean(result.cached) && !keepDraft && !keepCorrection,
              };
            }),
          );
          if (job.saveAfter && result.ready && result.taskId) {
            snapshot = {
              path: job.path,
              taskId: result.taskId,
              correction:
                appliedCorrection ??
                latestItems.current.find((item) => item.path === job.path)?.correction ??
                defaultMouthCorrection,
            };
          }
        } catch (failure) {
          if (isCurrent(job)) {
            const error = message(failure);
            update(
              job.path,
              job.kind === "save" ? { error } : { error, selected: false, applyFailed: job.kind === "apply" },
            );
          }
        }
        if (snapshot) {
          setBusy("save");
          try {
            await persist(job.name, [snapshot]);
          } catch (failure) {
            if (isCurrent(job)) update(job.path, { error: message(failure) });
          }
        }
      }
    } finally {
      lock.current = null;
      runningJob.current = undefined;
      setBusy(null);
      setActivePath("");
      setTask(null);
      syncPending();
      if (!jobs.current.length) {
        progress.current = { current: 0, total: 0 };
        setQueue({ ...progress.current });
      }
      setStopping(false);
    }
  }
  const pumpRef = useRef(pump);
  pumpRef.current = pump;
  useEffect(() => {
    if (!externalBusy) void pumpRef.current();
  }, [externalBusy]);

  const enqueue = async (paths: string[], options: MouthOptions, reanalysis: boolean, saveAfter = false) => {
    if (!paths.length) {
      setError("请至少选择一张立绘");
      return;
    }
    if (!saveAfter && lock.current && lock.current !== "generate") {
      setError("请等待当前操作完成");
      return;
    }
    setStopping(false);
    setError("");
    const pending = new Set(jobs.current.map((job) => job.path));
    const queuedPaths: string[] = [];
    for (const path of new Set(paths)) {
      if (path === runningJob.current?.path || pending.has(path)) continue;
      const job: MouthJob = { path, name, options, kind: reanalysis ? "apply" : "generate", saveAfter };
      if (reanalysis) jobs.current.unshift(job);
      else jobs.current.push(job);
      queuedPaths.push(path);
    }
    progress.current.total += queuedPaths.length;
    mutate((values) => {
      const existing = new Set(values.map((item) => item.path));
      const additions = queuedPaths
        .filter((path) => !existing.has(path))
        .map((path) => ({ path, selected: false, correction: { ...defaultMouthCorrection } }));
      return additions.length ? [...values, ...additions] : values;
    });
    setQueue({ ...progress.current });
    syncPending();
    await pumpRef.current();
  };
  const operate = async (kind: Busy, work: () => Promise<void>) => {
    if (lock.current || jobs.current.length || external.current) return;
    lock.current = kind;
    setBusy(kind);
    setError("");
    setTask(null);
    try {
      await work();
    } catch (failure) {
      setError(message(failure));
    } finally {
      lock.current = null;
      setBusy(null);
      setTask(null);
      void pumpRef.current();
    }
  };
  const refresh = async () => {
    try {
      setSetup(await spriteMouthRepository.status());
    } catch (failure) {
      setError(message(failure));
    }
  };
  const selected = items.filter(
    (item) => item.selected && !item.saved && !item.calibrationDirty && item.result?.ready && item.result.taskId,
  );
  const save = () =>
    operate("save", async () => {
      const snapshots = selected.map((item) => ({
        path: item.path,
        taskId: item.result!.taskId!,
        correction: item.correction,
      }));
      for (let index = 0; index < snapshots.length; index += MOUTH_SAVE_BATCH_SIZE) {
        if (name !== currentSource.current.name) return;
        await persist(name, snapshots.slice(index, index + MOUTH_SAVE_BATCH_SIZE));
      }
    });
  const finish = (path: string, options: MouthOptions | undefined, invalidFrames: string) => {
    const pending = [runningJob.current, ...jobs.current].find((job) => job?.path === path);
    if (pending) {
      if (pending.kind === "apply") pending.saveAfter = true;
      return;
    }
    const item = latestItems.current.find((candidate) => candidate.path === path);
    if (!item || item.saved) return;
    if (item.calibrationDirty) {
      if (options) void enqueue([path], options, true, true);
      else update(path, { error: invalidFrames });
    } else if (item.result?.ready && item.result.taskId) {
      jobs.current.unshift({
        kind: "save",
        path,
        name,
        item: { path, taskId: item.result.taskId, correction: item.correction },
      });
      progress.current.total += 1;
      setQueue({ ...progress.current });
      syncPending();
      void pumpRef.current();
    }
  };
  return {
    items,
    selected,
    selection,
    setSelection,
    setup,
    task,
    busy,
    externalBusy,
    error,
    queue,
    activePath,
    pendingPaths,
    stopping,
    refresh,
    save,
    finish,
    generate: (paths: string[], options: MouthOptions = {}) => enqueue(paths, options, false),
    reanalyse: (path: string, options: MouthOptions) => enqueue([path], options, true),
    configure: (input: { pythonPath?: string; device?: "auto" | "cpu" | "cuda" }) =>
      operate("setup", async () => setSetup(await spriteMouthRepository.configure(input))),
    download: () =>
      operate("setup", async () => setSetup(await spriteMouthRepository.download({ onTaskUpdate: setTask }))),
    install: () =>
      operate("setup", async () => setSetup(await spriteMouthRepository.install({ onTaskUpdate: setTask }))),
    importModels: (paths: string[]) =>
      operate("setup", async () => setSetup(await spriteMouthRepository.importModels({ paths }))),
    remove: (path: string) =>
      operate("remove", async () => {
        onSaved(await spriteMouthRepository.remove({ name, spritePath: path }));
        mutate((values) => values.filter((item) => item.path !== path));
      }),
    adjust: (path: string, correction: SpriteMouthCorrection) =>
      update(path, { correction, selected: true, saved: false }),
    editDraft: (path: string, draft: MouthCalibrationDraft) =>
      update(path, { draft, calibrationDirty: true, applyFailed: false, selected: false, saved: false }),
    select: (path: string, selected: boolean) => update(path, { selected }),
    discard: (path: string) => mutate((values) => values.filter((item) => item.path !== path)),
    stop: () => {
      setStopping(Boolean(lock.current));
      const kept = jobs.current.filter((job) => job.kind !== "generate");
      progress.current.total -= jobs.current.length - kept.length;
      jobs.current = kept;
      syncPending();
      if (!lock.current && !jobs.current.length) progress.current = { current: 0, total: 0 };
      setQueue({ ...progress.current });
    },
    hasDrafts: items.some((item) => !item.saved) || pendingPaths.length > 0,
  };
}

export type SpriteMouthController = ReturnType<typeof useSpriteMouths>;
