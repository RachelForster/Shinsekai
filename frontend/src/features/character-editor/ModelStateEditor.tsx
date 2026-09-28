import { useEffect, useRef, useState } from "react";
import type { Character } from "../../shared/platform/types";
import { getPlatform } from "../../shared/platform/platform";
import { registeredAvatarFormats, avatarFormat } from "../../entities/character-visual/registry";
import { avatarAssetUrl } from "../../entities/character-visual/assetUrl";
import type { AvatarModule, AvatarSession } from "../../entities/character-visual/contracts";
import { tagContents } from "../../shared/assets/assetText";

export function ModelStateEditor({
  character,
  onChange,
  onSaved,
}: {
  character: Character;
  onChange: (character: Character) => void;
  onSaved: (character: Character) => void;
}) {
  const kind = character.avatar_type;
  const bank = character.avatars[kind];
  const format = avatarFormat(kind);
  const host = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState("");
  const [index, setIndex] = useState(-1);
  const [tags, setTags] = useState("");
  const [session, setSession] = useState<AvatarSession<unknown, unknown> | null>(null);
  const [module, setModule] = useState<AvatarModule<unknown, unknown> | null>(null);
  const [value, setValue] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const request = useRef(0);
  const name = character.name;
  const modelPath = bank?.model_path ?? "";
  const path = index >= 0 ? (bank?.sprites[index]?.path ?? "") : "";
  useEffect(() => {
    setTags(index >= 0 ? (tagContents(bank?.emotion_tags ?? "", bank?.sprites.length ?? 0)[index] ?? "") : "");
  }, [index, bank?.emotion_tags, bank?.sprites.length]);
  const run = async (operation: () => Promise<void>) => {
    setPending(true);
    setError("");
    try {
      await operation();
    } catch (failure) {
      setError(String(failure));
    } finally {
      setPending(false);
    }
  };
  useEffect(() => {
    setIndex(-1);
    setTags("");
    setSource("");
    ++request.current;
  }, [name, kind, modelPath]);
  useEffect(() => {
    if (!host.current || !format || !modelPath) {
      setSession(null);
      return;
    }
    const target = host.current;
    const abort = new AbortController();
    let instance: AvatarSession<unknown, unknown> | null = null;
    let observer: ResizeObserver | null = null;
    setSession(null);
    setError("");
    setValue(null);
    void format
      .load()
      .then(async (loaded) => {
        if (abort.signal.aborted) return;
        const modelUrl = getPlatform().files.modelUrl(modelPath, modelPath.replaceAll("\\", "/").split("/").at(-1)!);
        instance = await loaded.create(
          {
            element: target,
            modelUrl,
            assetUrl: (relative) => avatarAssetUrl(modelUrl, relative),
            reportError: (failure) => {
              if (!abort.signal.aborted) setError(failure.message);
            },
          },
          abort.signal,
        );
        if (abort.signal.aborted) {
          instance.dispose();
          return;
        }
        const resize = () => instance?.resize(target.clientWidth, target.clientHeight);
        resize();
        observer = new ResizeObserver(resize);
        observer.observe(target);
        setModule(loaded);
        setSession(instance);
      })
      .catch((failure) => {
        if (!abort.signal.aborted) setError(String(failure));
      });
    return () => {
      abort.abort();
      ++request.current;
      observer?.disconnect();
      instance?.dispose();
    };
  }, [name, kind, modelPath, format]);
  useEffect(() => {
    if (!session || !modelPath) return;
    const abort = new AbortController();
    const sequence = ++request.current;
    setValue(null);
    void (async () => {
      let state = session.readState();
      if (path) {
        const normalizedModel = modelPath.replaceAll("\\", "/");
        const relative = path.replaceAll("\\", "/").slice(normalizedModel.lastIndexOf("/") + 1);
        const response = await fetch(getPlatform().files.modelUrl(modelPath, relative), { signal: abort.signal });
        if (!response.ok) throw new Error(`State request failed: ${response.status}`);
        state = await response.json();
      }
      abort.signal.throwIfAborted();
      await session.apply(state, "edit", abort.signal);
      if (request.current === sequence && !abort.signal.aborted) setValue(session.readState());
    })().catch((failure) => {
      if (!abort.signal.aborted) setError(String(failure));
    });
    return () => abort.abort();
  }, [session, path, modelPath]);
  const change = (state: unknown) => {
    if (!session) return;
    const sequence = ++request.current;
    void session
      .apply(state, "edit", new AbortController().signal)
      .then(() => {
        if (sequence === request.current) {
          setValue(session.readState());
          setError("");
        }
      })
      .catch((failure) => setError(String(failure)));
  };
  const Editor = module?.Editor;
  return (
    <section className="page-section" id="character-model">
      <h2>人物形象 / Avatar</h2>
      <label>
        类型 / Format{" "}
        <select
          aria-label="Avatar format"
          value={kind}
          onChange={(event) => {
            const avatar_type = event.target.value;
            onChange({
              ...character,
              avatar_type,
              avatars: {
                ...character.avatars,
                ...(avatar_type !== "static" && !character.avatars[avatar_type]
                  ? { [avatar_type]: avatarFormat(avatar_type)!.createEmpty() }
                  : {}),
              },
            });
          }}
        >
          <option value="static">静态 / Static</option>
          {registeredAvatarFormats().map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
          {kind !== "static" && !format && (
            <option value={kind} disabled>
              {kind}：不可用 / Unavailable
            </option>
          )}
        </select>
      </label>
      {kind !== "static" && format && (
        <>
          <p>先保存角色；模型更换后旧状态保留，需要重新校验。选择将在下次聊天生效。</p>
          <label>
            本地模型入口 / Model entry
            <input
              aria-label="Model entry"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder=".../model.model3.json"
            />
          </label>
          <button
            type="button"
            disabled={pending || !source || !name}
            onClick={() =>
              void run(async () => {
                const sequence = ++request.current;
                const result = await getPlatform().characters.importModel({
                  name,
                  avatar_type: kind,
                  source_path: source,
                });
                if (request.current === sequence) onSaved(result);
              })
            }
          >
            导入模型 / Import model
          </button>
          <div ref={host} style={{ height: 400, width: "100%" }} />
          <select
            aria-label="Model state"
            value={index}
            onChange={(event) => {
              setIndex(Number(event.target.value));
              setTags("");
            }}
          >
            <option value={-1}>新状态 / New state</option>
            {bank?.sprites.map((sprite, i) => (
              <option key={sprite.path} value={i}>
                {i + 1}: {sprite.path.split(/[\\/]/).at(-1)}
              </option>
            ))}
          </select>
          {session && Editor && value !== null && <Editor session={session} value={value} onChange={change} />}
          <label>
            标签 / Tags
            <input value={tags} onChange={(event) => setTags(event.target.value)} />
          </label>
          <button
            type="button"
            disabled={pending || !session || value === null || Boolean(error)}
            onClick={() =>
              void run(async () => {
                if (!session) return;
                const sequence = ++request.current;
                const state = session.readState();
                const result = await getPlatform().characters.saveModelState({
                  name,
                  avatar_type: kind,
                  model_path: modelPath,
                  sprite_index: index,
                  path,
                  state,
                  tags,
                });
                if (request.current === sequence) onSaved(result);
              })
            }
          >
            保存状态 / Save state
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
