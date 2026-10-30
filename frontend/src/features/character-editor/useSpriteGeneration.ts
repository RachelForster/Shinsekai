import { useRef, useState } from "react";

import {
  importGeneratedCharacterSprites,
  captureCharacterSpriteFrame,
  planCharacterSprites,
  renderCharacterSprite,
  removeCharacterSpriteBackground,
  animateCharacterSprite,
} from "../../entities/character/repository";
import type {
  Character,
  CharacterSpriteAnimationInput,
  GeneratedCharacterSprite,
  SpritePromptPair,
  TaskSnapshot,
} from "../../shared/platform/types";

export interface SpriteCandidate extends SpritePromptPair {
  id: string;
  result?: GeneratedCharacterSprite;
  selected: boolean;
  error: string;
  animationInput?: CharacterSpriteAnimationInput;
  manual?: boolean;
}

export function useSpriteGeneration(
  name: string,
  setting: string,
  onImported: (character: Character, replacedIndex?: number) => void,
) {
  const [items, setItems] = useState<SpriteCandidate[]>([]);
  const [busy, setBusy] = useState<"plan" | "render" | "frame" | "cutout" | "import" | "animate" | null>(null);
  const [activeId, setActiveId] = useState("");
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [error, setError] = useState("");
  const [stopping, setStopping] = useState(false);
  const [queue, setQueue] = useState<{ current: number; total: number } | null>(null);
  const locked = useRef(false);
  const stopRequested = useRef(false);
  const update = (id: string, patch: Partial<SpriteCandidate>) =>
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

  const operate = async (kind: NonNullable<typeof busy>, work: () => Promise<void>) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(kind);
    setError("");
    setTask(null);
    try {
      await work();
    } catch (error) {
      setError(message(error));
    } finally {
      locked.current = false;
      setBusy(null);
      setActiveId("");
      setTask(null);
      setQueue(null);
      setStopping(false);
    }
  };

  const processQueue = async <T>(candidates: T[], work: (item: T) => Promise<void>) => {
    stopRequested.current = false;
    setStopping(false);
    for (const [index, candidate] of candidates.entries()) {
      if (stopRequested.current) break;
      setQueue({ current: index + 1, total: candidates.length });
      setTask(null);
      await work(candidate);
    }
  };

  const plan = (count: number, requirements: string, referenceImage: string) =>
    operate("plan", async () => {
      const result = await planCharacterSprites(
        { name, setting, count, requirements, referenceImage },
        { onTaskUpdate: setTask },
      );
      setItems((current) => [
        ...current,
        ...result.items.map((item) => ({ ...item, id: crypto.randomUUID(), selected: false, error: "" })),
      ]);
    });

  const render = (candidates: SpriteCandidate[], referenceImage: string, removeBackground = true) =>
    operate("render", () =>
      // Keep requests sequential: each result can fail or be retried independently.
      processQueue(candidates, async (item) => {
        setActiveId(item.id);
        update(item.id, { error: "" });
        try {
          const result = await renderCharacterSprite(
            { name, prompt: item.prompt, tagging: item.tagging, referenceImage, removeBackground },
            { onTaskUpdate: setTask },
          );
          update(item.id, { result, prompt: result.prompt, tagging: result.tagging, selected: true, manual: false });
        } catch (error) {
          update(item.id, { error: message(error) });
        }
      }),
    );

  const selected = items.filter(
    (item) =>
      item.selected &&
      item.result &&
      item.result.prompt === item.prompt &&
      item.tagging.trim() &&
      (!item.animationInput || item.result.alphaVerified),
  );
  const addManual = (animationInput?: CharacterSpriteAnimationInput) => {
    if (locked.current || items.length >= 12) return;
    setItems((current) =>
      current.length >= 12
        ? current
        : [
            ...current,
            {
              id: crypto.randomUUID(),
              prompt: "",
              tagging: animationInput?.tagging || "平静，站立",
              selected: false,
              error: "",
              manual: true,
              ...(animationInput ? { animationInput: { ...animationInput, customPrompt: "" } } : {}),
            },
          ],
    );
  };
  const queueAnimations = (entries: { input: CharacterSpriteAnimationInput; existing?: SpriteCandidate }[]) =>
    operate("animate", async () => {
      const additions = entries.filter((entry) => !entry.existing).length;
      if (items.length + additions > 12) throw new Error("每次最多保留 12 个方案，请先添加或移除部分方案。");
      const candidates = entries.map(({ input, existing }) => ({
        input: { ...input, tagging: existing?.tagging ?? input.tagging },
        item: existing ?? {
          id: crypto.randomUUID(),
          prompt: "",
          tagging: input.tagging,
          selected: false,
          error: "",
          animationInput: { ...input },
        },
        fresh: !existing,
      }));
      setItems((current) => [
        ...current,
        ...candidates.filter((candidate) => candidate.fresh).map((candidate) => candidate.item),
      ]);
      await processQueue(candidates, async ({ input, item }) => {
        setActiveId(item.id);
        update(item.id, { error: "" });
        try {
          const result = await animateCharacterSprite(input, { onTaskUpdate: setTask });
          update(item.id, {
            result,
            prompt: result.prompt,
            tagging: result.tagging,
            selected: Boolean(result.alphaVerified),
            manual: false,
          });
        } catch (error) {
          update(item.id, { error: message(error) });
        }
      });
    });
  const animate = (input: CharacterSpriteAnimationInput, existing?: SpriteCandidate) =>
    queueAnimations([{ input, existing }]);
  const animateBatch = (inputs: CharacterSpriteAnimationInput[]) => queueAnimations(inputs.map((input) => ({ input })));
  const animatePending = (candidates: SpriteCandidate[]) =>
    queueAnimations(
      candidates.flatMap((item) =>
        item.animationInput &&
        (!item.result || item.result.prompt !== item.prompt) &&
        (item.animationInput.customPrompt === undefined || item.prompt.trim()) &&
        item.tagging.trim()
          ? [{ input: item.animationInput, existing: item }]
          : [],
      ),
    );
  const capture = (item: SpriteCandidate, seconds: number, removeBackground = true) =>
    operate("frame", async () => {
      if (!item.result || item.result.prompt !== item.prompt) return;
      setActiveId(item.id);
      update(item.id, { error: "" });
      try {
        const result = await captureCharacterSpriteFrame(
          { name, taskId: item.result.taskId, seconds, removeBackground },
          { onTaskUpdate: setTask },
        );
        update(item.id, { result, selected: true });
      } catch (error) {
        update(item.id, { error: message(error) });
      }
    });
  const cutout = (item: SpriteCandidate) =>
    operate("cutout", async () => {
      if (!item.result || item.result.prompt !== item.prompt) return;
      setActiveId(item.id);
      update(item.id, { error: "" });
      try {
        const result = await removeCharacterSpriteBackground(
          { name, taskId: item.result.taskId },
          { onTaskUpdate: setTask },
        );
        update(item.id, { result, selected: true });
      } catch (error) {
        update(item.id, { error: message(error) });
      }
    });
  const save = (candidates = selected) =>
    operate("import", async () => {
      if (!candidates.length) return;
      const character = await importGeneratedCharacterSprites({
        name,
        items: candidates.map((item) => ({ taskId: item.result!.taskId, tagging: item.tagging })),
      });
      const ids = new Set(candidates.map((item) => item.id));
      setItems((current) => current.filter((item) => !ids.has(item.id)));
      onImported(character);
    });
  const replace = async (item: SpriteCandidate, index: number, path: string) => {
    if (
      !item.result ||
      item.result.prompt !== item.prompt ||
      !item.tagging.trim() ||
      (item.animationInput && !item.result.alphaVerified)
    )
      return false;
    let saved = false;
    await operate("import", async () => {
      const character = await importGeneratedCharacterSprites({
        name,
        items: [{ taskId: item.result!.taskId, tagging: item.tagging }],
        replace: { index, path },
      });
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
      onImported(character, index);
      saved = true;
    });
    return saved;
  };
  return {
    items,
    busy,
    activeId,
    task,
    error,
    stopping,
    queue,
    selected,
    update,
    addManual,
    plan,
    render,
    animate,
    animateBatch,
    animatePending,
    capture,
    cutout,
    save,
    replace,
    clearError: () => setError(""),
    stop: () => {
      stopRequested.current = true;
      setStopping(true);
    },
    selectAll: (selected: boolean, candidates = items) =>
      setItems((current) =>
        current.map((item) => ({
          ...item,
          selected: candidates.some((candidate) => candidate.id === item.id)
            ? selected &&
              Boolean(
                item.result &&
                item.result.prompt === item.prompt &&
                item.tagging.trim() &&
                (!item.animationInput || item.result.alphaVerified),
              )
            : item.selected,
        })),
      ),
    remove: (id: string) => setItems((current) => current.filter((item) => item.id !== id)),
  };
}
