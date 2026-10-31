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
  SpriteMattingOptions,
} from "../../shared/platform/types";

export interface SpriteCandidate extends SpritePromptPair {
  id: string;
  result?: GeneratedCharacterSprite;
  selected: boolean;
  error: string;
  animationInput?: CharacterSpriteAnimationInput;
  manual?: boolean;
  original?: { index: number; path: string };
}

export function useSpriteGeneration(
  name: string,
  setting: string,
  onImported: (character: Character, replacedIndex?: number | number[]) => void,
  sprites: Character["sprites"],
  mattingOptions: SpriteMattingOptions,
) {
  const [items, setItems] = useState<SpriteCandidate[]>([]);
  const [busy, setBusy] = useState<"plan" | "render" | "frame" | "cutout" | "import" | "replace" | "animate" | null>(
    null,
  );
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
  const originalFor = (reference: string) => {
    if (!reference) return undefined;
    const matches = sprites.flatMap((sprite, index) => (sprite.path === reference ? [{ index, path: reference }] : []));
    if (matches.length === 1) return matches[0];
    return items.find((item) => item.result?.path === reference)?.original;
  };

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
            {
              name,
              prompt: item.prompt,
              tagging: item.tagging,
              referenceImage,
              removeBackground,
              mattingModel: mattingOptions.mattingModel,
            },
            { onTaskUpdate: setTask },
          );
          update(item.id, {
            result,
            prompt: result.prompt,
            tagging: result.tagging,
            selected: true,
            manual: false,
            original: originalFor(referenceImage),
          });
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
        input: { ...input, ...mattingOptions, tagging: existing?.tagging ?? input.tagging },
        item: existing ?? {
          id: crypto.randomUUID(),
          prompt: "",
          tagging: input.tagging,
          selected: false,
          error: "",
          animationInput: { ...input },
        },
        fresh: !existing,
        original: existing?.original ?? originalFor(input.referenceImage),
      }));
      setItems((current) => [
        ...current,
        ...candidates.filter((candidate) => candidate.fresh).map((candidate) => candidate.item),
      ]);
      await processQueue(candidates, async ({ input, item, original }) => {
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
            original,
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
          { name, taskId: item.result.taskId, seconds, removeBackground, mattingModel: mattingOptions.mattingModel },
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
          {
            name,
            taskId: item.result.taskId,
            ...(item.animationInput ? mattingOptions : { mattingModel: mattingOptions.mattingModel }),
          },
          { onTaskUpdate: setTask },
        );
        update(item.id, { result, selected: true });
      } catch (error) {
        update(item.id, { error: message(error) });
      }
    });
  const persist = async (
    candidates: SpriteCandidate[],
    replacements?: { index: number; path: string }[],
    singleReplace = false,
  ) => {
    if (
      !candidates.length ||
      candidates.some(
        (item) =>
          !item.result ||
          item.result.prompt !== item.prompt ||
          !item.tagging.trim() ||
          (item.animationInput && !item.result.alphaVerified),
      )
    )
      return false;
    let saved = false;
    await operate(replacements ? "replace" : "import", async () => {
      const character = await importGeneratedCharacterSprites({
        name,
        items: candidates.map((item, index) => ({
          taskId: item.result!.taskId,
          tagging: item.tagging,
          ...(replacements && !singleReplace ? { replace: replacements[index] } : {}),
        })),
        ...(singleReplace ? { replace: replacements![0] } : {}),
      });
      const ids = new Set(candidates.map((item) => item.id));
      setItems((current) => current.filter((item) => !ids.has(item.id)));
      if (replacements) {
        onImported(
          character,
          replacements.length === 1 ? replacements[0].index : replacements.map((item) => item.index),
        );
      } else onImported(character);
      saved = true;
    });
    return saved;
  };
  const save = (candidates = selected) => persist(candidates);
  const replace = (item: SpriteCandidate, index: number, path: string) => persist([item], [{ index, path }], true);
  const replaceSelected = (candidates: SpriteCandidate[]) => {
    const targets = candidates.flatMap((item) => (item.original ? [item.original] : []));
    if (
      targets.length !== candidates.length ||
      targets.some((target) => sprites[target.index]?.path !== target.path) ||
      new Set(targets.map((target) => target.index)).size !== targets.length
    )
      return Promise.resolve(false);
    return persist(candidates, targets);
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
    replaceSelected,
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
