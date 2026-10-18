import { useRef, useState } from "react";

import {
  importGeneratedCharacterSprites,
  planCharacterSprites,
  renderCharacterSprite,
} from "../../entities/character/repository";
import type { Character, GeneratedCharacterSprite, SpritePromptPair, TaskSnapshot } from "../../shared/platform/types";

export interface SpriteCandidate extends SpritePromptPair {
  id: string;
  result?: GeneratedCharacterSprite;
  selected: boolean;
  error: string;
}

export function useSpriteGeneration(name: string, setting: string, onImported: (character: Character) => void) {
  const [items, setItems] = useState<SpriteCandidate[]>([]);
  const [busy, setBusy] = useState<"plan" | "render" | "import" | null>(null);
  const [activeId, setActiveId] = useState("");
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [error, setError] = useState("");
  const [stopping, setStopping] = useState(false);
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

  const render = (candidates: SpriteCandidate[], referenceImage: string) =>
    operate("render", async () => {
      stopRequested.current = false;
      setStopping(false);
      // Keep requests sequential: each result can fail or be retried independently.
      for (const item of candidates) {
        if (stopRequested.current) break;
        setActiveId(item.id);
        setTask(null);
        update(item.id, { error: "" });
        try {
          const result = await renderCharacterSprite(
            { name, prompt: item.prompt, tagging: item.tagging, referenceImage },
            { onTaskUpdate: setTask },
          );
          update(item.id, { result, prompt: result.prompt, tagging: result.tagging, selected: true });
        } catch (error) {
          update(item.id, { error: message(error) });
        }
      }
      setStopping(false);
    });

  const selected = items.filter(
    (item) => item.selected && item.result && item.result.prompt === item.prompt && item.tagging.trim(),
  );
  const save = () =>
    operate("import", async () => {
      if (!selected.length) return;
      const character = await importGeneratedCharacterSprites({
        name,
        items: selected.map((item) => ({ taskId: item.result!.taskId, tagging: item.tagging })),
      });
      const ids = new Set(selected.map((item) => item.id));
      setItems((current) => current.filter((item) => !ids.has(item.id)));
      onImported(character);
    });
  return {
    items,
    busy,
    activeId,
    task,
    error,
    stopping,
    selected,
    update,
    plan,
    render,
    save,
    stop: () => {
      stopRequested.current = true;
      setStopping(true);
    },
    selectAll: (selected: boolean) =>
      setItems((current) =>
        current.map((item) => ({
          ...item,
          selected: selected && Boolean(item.result && item.result.prompt === item.prompt && item.tagging.trim()),
        })),
      ),
    remove: (id: string) => setItems((current) => current.filter((item) => item.id !== id)),
  };
}
