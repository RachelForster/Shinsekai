import { useEffect, useRef, useState } from "react";
import type { Character } from "../../entities/config/types";
import { importCharacterModel, saveCharacterModelState } from "../../entities/character/repository";
import { modelFileUrl } from "../../entities/files/repository";
import { registeredAvatarFormats, avatarFormat } from "../../entities/character-visual/registry";
import { avatarAssetUrl } from "../../entities/character-visual/assetUrl";
import type { AvatarModule, AvatarSession } from "../../entities/character-visual/contracts";
import { readAvatarState } from "../../entities/character-visual/repository";
import { tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, FilePicker, Select, TextInput } from "../../shared/ui";
import "./ModelStateEditor.css";

export function ModelStateEditor({
  character,
  onChange,
  onSaved,
}: {
  character: Character;
  onChange: (character: Character) => void;
  onSaved: (character: Character) => void;
}) {
  const { t } = useI18n();
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
        const modelUrl = modelFileUrl(modelPath);
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
        state = await readAvatarState(modelPath, path, abort.signal);
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
    <section className="section page-section-anchor" id="character-model">
      <div className="section__header">
        <h2 className="section__title">{t("character.avatar.title")}</h2>
      </div>
      <div className="asset-editor">
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("character.avatar.format")}</span>
          <span className="field-row__control">
            <Select
              aria-label={t("character.avatar.format")}
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
              <option value="static">{t("character.avatar.static")}</option>
              {registeredAvatarFormats().map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
              {kind !== "static" && !format && (
                <option value={kind} disabled>
                  {t("character.avatar.unavailable", { format: kind })}
                </option>
              )}
            </Select>
          </span>
        </label>
        {kind !== "static" && format && (
          <>
            <p className="field-row__hint">{t("character.avatar.importHint")}</p>
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("character.avatar.modelEntry")}</span>
              <span className="field-row__control">
                <FilePicker
                  aria-label={t("character.avatar.modelEntry")}
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                  onPathChange={setSource}
                  acceptedExtensions={format.modelExtensions}
                  disabled={pending}
                  pickLabel={t("common.chooseFile")}
                  pickerTitle={t("character.avatar.modelEntry")}
                />
              </span>
            </label>
            <AsyncButton
              loading={pending}
              disabled={pending || !source || !name}
              onClick={() =>
                void run(async () => {
                  const sequence = ++request.current;
                  const result = await importCharacterModel({
                    name,
                    avatar_type: kind,
                    source_path: source,
                  });
                  if (request.current === sequence) onSaved(result);
                })
              }
            >
              {t("character.avatar.importModel")}
            </AsyncButton>
            <div ref={host} className="model-state-editor__preview" />
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("character.avatar.state")}</span>
              <span className="field-row__control">
                <Select
                  aria-label={t("character.avatar.state")}
                  value={index}
                  onChange={(event) => {
                    setIndex(Number(event.target.value));
                    setTags("");
                  }}
                >
                  <option value={-1}>{t("character.avatar.newState")}</option>
                  {bank?.sprites.map((sprite, i) => (
                    <option key={sprite.path} value={i}>
                      {i + 1}: {sprite.path.split(/[\\/]/).at(-1)}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
            {session && Editor && value !== null && <Editor session={session} value={value} onChange={change} />}
            <label className="field-row field-row--stack">
              <span className="field-row__label">{t("character.sprite.tag")}</span>
              <span className="field-row__control">
                <TextInput value={tags} onChange={(event) => setTags(event.target.value)} />
              </span>
            </label>
            <AsyncButton
              loading={pending}
              disabled={pending || !session || value === null || Boolean(error)}
              onClick={() =>
                void run(async () => {
                  if (!session) return;
                  const sequence = ++request.current;
                  const state = session.readState();
                  const result = await saveCharacterModelState({
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
              {t("character.avatar.saveState")}
            </AsyncButton>
          </>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
