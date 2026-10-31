import { useEffect, useRef, useState } from "react";

import {
  analyzeSpriteTransitions,
  generateSpriteTransition,
  saveSpriteTransitions,
} from "../../entities/character/repository";
import { SPRITE_TRANSITION_FRAME_COUNT } from "../../shared/assets/spriteTransition";
import { useI18n } from "../../shared/i18n";
import type {
  Character,
  GeneratedSpriteTransition,
  SpriteTransitionAnalysis,
  TaskSnapshot,
  SpriteMattingOptions,
} from "../../shared/platform/types";

export interface TransitionCandidate {
  id: string;
  fromPath: string;
  toPath: string;
  result?: GeneratedSpriteTransition;
  saved?: boolean;
  selected?: boolean;
  error?: string;
}

export const transitionKey = (from: string, to: string) => JSON.stringify([from, to]);

export function transitionPairs(paths: string[]): TransitionCandidate[] {
  const unique = [...new Set(paths)];
  return unique.flatMap((fromPath) =>
    unique
      .filter((toPath) => toPath !== fromPath)
      .map((toPath) => ({
        id: transitionKey(fromPath, toPath),
        fromPath,
        toPath,
      })),
  );
}

export function useSpriteTransitions(
  character: Character,
  name: string,
  onSaved: (character: Character) => void,
  mattingOptions: SpriteMattingOptions,
) {
  const { t } = useI18n();
  const [sourceSelection, setSourceSelection] = useState<string[]>([]);
  const [items, setItems] = useState<TransitionCandidate[]>(() =>
    (character.sprite_transitions ?? [])
      .filter(
        (edge) =>
          character.sprites.some((sprite) => sprite.path === edge.from_path) &&
          character.sprites.some((sprite) => sprite.path === edge.to_path),
      )
      .map((edge) => ({
        id: transitionKey(edge.from_path, edge.to_path),
        fromPath: edge.from_path,
        toPath: edge.to_path,
        saved: true,
        result: {
          name,
          fromPath: edge.from_path,
          toPath: edge.to_path,
          taskId: "",
          path: edge.path,
          alphaVerified: true,
          cached: true,
          frameCount: edge.frame_count ?? 5,
        },
      })),
  );
  const [busy, setBusy] = useState<"transition-generate" | "transition-save" | "transition-analyze" | null>(null);
  const [task, setTask] = useState<TaskSnapshot<GeneratedSpriteTransition | SpriteTransitionAnalysis> | null>(null);
  const [analysis, setAnalysis] = useState<SpriteTransitionAnalysis | null>(null);
  const [planningMode, setPlanningMode] = useState<"manual" | "recommended">("manual");
  const [recommendationCount, setRecommendationCount] = useState("20");
  const [skipExisting, setSkipExisting] = useState(true);
  const [recommendedSelection, setRecommendedSelection] = useState<string[]>([]);
  const [queue, setQueue] = useState({ current: 0, total: 0 });
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState("");
  const spritePaths = JSON.stringify(character.sprites.map((sprite) => sprite.path));
  const catalogKey = JSON.stringify([name, spritePaths, character.emotion_tags]);
  const currentCatalog = useRef(catalogKey);
  currentCatalog.current = catalogKey;
  useEffect(() => {
    const paths = new Set<string>(JSON.parse(spritePaths));
    setItems((current) => current.filter((item) => paths.has(item.fromPath) && paths.has(item.toPath)));
    setSourceSelection((current) => current.filter((path) => paths.has(path)));
  }, [spritePaths]);
  useEffect(() => {
    setAnalysis(null);
    setRecommendedSelection([]);
    setPlanningMode("manual");
  }, [catalogKey]);
  const lock = useRef(false);
  const stopRef = useRef(false);
  const update = (id: string, patch: Partial<TransitionCandidate>) =>
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));

  const isReady = (fromPath: string, toPath: string, result = analysis) =>
    Boolean(result?.items.some((item) => item.fromPath === fromPath && item.toPath === toPath && item.existing)) ||
    items.some(
      (item) =>
        item.id === transitionKey(fromPath, toPath) &&
        item.result?.taskId &&
        item.result.alphaVerified &&
        item.result.frameCount === SPRITE_TRANSITION_FRAME_COUNT &&
        !item.error,
    );
  const chooseTop = (result = analysis, count = recommendationCount, skip = skipExisting) => {
    const limit = Number(count);
    setRecommendedSelection(
      result && Number.isSafeInteger(limit) && limit > 0
        ? result.items
            .filter((item) => !skip || !isReady(item.fromPath, item.toPath, result))
            .slice(0, limit)
            .map((item) => transitionKey(item.fromPath, item.toPath))
        : [],
    );
  };
  const analyze = async () => {
    if (lock.current) return;
    const catalog = currentCatalog.current;
    lock.current = true;
    setBusy("transition-analyze");
    setTask(null);
    setError("");
    try {
      const result = await analyzeSpriteTransitions({ name }, { onTaskUpdate: setTask });
      if (currentCatalog.current !== catalog) return;
      if (JSON.stringify(result.spritePaths) !== spritePaths) throw new Error(t("spriteTransition.saveCollection"));
      setAnalysis(result);
      setPlanningMode("recommended");
      chooseTop(result);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      lock.current = false;
      setBusy(null);
      setTask(null);
    }
  };
  const recommendedPairs: TransitionCandidate[] = (analysis?.items ?? [])
    .filter(
      (item) =>
        recommendedSelection.includes(transitionKey(item.fromPath, item.toPath)) &&
        (!skipExisting || !isReady(item.fromPath, item.toPath)),
    )
    .map((item) => ({ id: transitionKey(item.fromPath, item.toPath), fromPath: item.fromPath, toPath: item.toPath }));

  const generate = async (pairs: TransitionCandidate[], regenerate = false, retryMatting = false) => {
    if (lock.current || !pairs.length) return;
    lock.current = true;
    stopRef.current = false;
    setStopping(false);
    setBusy("transition-generate");
    setError("");
    const pending = pairs.filter(
      (pair) =>
        retryMatting ||
        regenerate ||
        pair.saved ||
        !pair.result?.alphaVerified ||
        pair.result.frameCount !== SPRITE_TRANSITION_FRAME_COUNT,
    );
    setItems((current) => [...current, ...pairs.filter((pair) => !current.some((item) => item.id === pair.id))]);
    try {
      for (const [index, pair] of pending.entries()) {
        if (stopRef.current) break;
        setQueue({ current: index + 1, total: pending.length });
        setTask(null);
        update(pair.id, { error: undefined });
        try {
          const result = await generateSpriteTransition(
            {
              name,
              fromPath: pair.fromPath,
              toPath: pair.toPath,
              regenerate,
              ...mattingOptions,
              ...((retryMatting || (!regenerate && !pair.result?.alphaVerified)) &&
              pair.result?.taskId &&
              pair.result.requestedFrames === SPRITE_TRANSITION_FRAME_COUNT
                ? { retryTaskId: pair.result.taskId }
                : {}),
            },
            { onTaskUpdate: setTask },
          );
          update(pair.id, { result, saved: Boolean(result.cached), selected: result.alphaVerified && !result.cached });
        } catch (failure) {
          update(pair.id, { error: failure instanceof Error ? failure.message : String(failure) });
        }
      }
    } finally {
      lock.current = false;
      setBusy(null);
      setTask(null);
      setStopping(false);
    }
  };

  const selected = items.filter(
    (item) =>
      item.selected &&
      !item.saved &&
      item.result?.alphaVerified &&
      item.result.frameCount === SPRITE_TRANSITION_FRAME_COUNT,
  );
  const save = async () => {
    if (lock.current || !selected.length) return;
    lock.current = true;
    setBusy("transition-save");
    setError("");
    try {
      const saved = await saveSpriteTransitions({
        name,
        items: selected.map((item) => ({ taskId: item.result!.taskId })),
      });
      setItems((current) =>
        current.map((item) => {
          if (!selected.some((chosen) => chosen.id === item.id)) return item;
          const edge = saved.sprite_transitions?.find(
            (edge) => edge.from_path === item.fromPath && edge.to_path === item.toPath,
          );
          return {
            ...item,
            selected: false,
            saved: true,
            result: edge && item.result ? { ...item.result, path: edge.path } : item.result,
          };
        }),
      );
      onSaved(saved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      lock.current = false;
      setBusy(null);
    }
  };

  return {
    analysis,
    analyze,
    planningMode,
    setPlanningMode,
    recommendationCount,
    setRecommendationCount: (value: string) => {
      setRecommendationCount(value);
      chooseTop(analysis, value);
    },
    skipExisting,
    setSkipExisting: (value: boolean) => {
      setSkipExisting(value);
      chooseTop(analysis, recommendationCount, value);
    },
    chooseTop: () => chooseTop(),
    isReady,
    recommendedPairs,
    toggleRecommendation: (id: string) =>
      setRecommendedSelection((current) =>
        current.includes(id) ? current.filter((key) => key !== id) : [...current, id],
      ),
    sourceSelection,
    setSourceSelection,
    items,
    busy,
    task,
    queue,
    stopping,
    error,
    selected,
    generate,
    save,
    update,
    hasDrafts: items.some((item) => !item.saved),
    stop: () => {
      stopRef.current = true;
      setStopping(true);
    },
  };
}

export type SpriteTransitionController = ReturnType<typeof useSpriteTransitions>;
