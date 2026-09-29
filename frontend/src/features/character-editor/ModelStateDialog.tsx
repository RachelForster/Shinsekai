import { useEffect, useRef, useState } from "react";
import type { Character } from "../../entities/config/types";
import { characterAvatarType, getCharacterAssets } from "../../entities/character/assets";
import { saveCharacterModelState } from "../../entities/character/repository";
import { modelFileUrl } from "../../entities/files/repository";
import { avatarFormat } from "../../entities/character-visual/registry";
import { avatarAssetUrl } from "../../entities/character-visual/assetUrl";
import type { AvatarModule, AvatarSession } from "../../entities/character-visual/contracts";
import { readAvatarState } from "../../entities/character-visual/repository";
import { tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Dialog, TextInput } from "../../shared/ui";

/** A temporary edit session: closing discards drafts; only Save changes the resource bank. */
export function ModelStateDialog({
  character,
  index,
  onClose,
  onSaved,
}: {
  character: Character;
  index: number;
  onClose: () => void;
  onSaved: (character: Character) => void;
}) {
  const { t } = useI18n();
  const kind = characterAvatarType(character);
  const bank = getCharacterAssets(character);
  const format = avatarFormat(kind);
  const modelPath = bank.model_path;
  const path = index >= 0 ? (bank.sprites[index]?.path ?? "") : "";
  const host = useRef<HTMLDivElement>(null);
  const [tags, setTags] = useState(
    index >= 0 ? (tagContents(bank.emotion_tags, bank.sprites.length)[index] ?? "") : "",
  );
  const [session, setSession] = useState<AvatarSession<unknown, unknown> | null>(null);
  const [module, setModule] = useState<AvatarModule<unknown, unknown> | null>(null);
  const [value, setValue] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [pending, setPending] = useState(false);
  const [applying, setApplying] = useState(false);
  const request = useRef(0);
  const lifetime = useRef<AbortController | null>(null);
  useEffect(() => {
    const target = host.current;
    if (!target || !format) return;
    const abort = new AbortController();
    lifetime.current = abort;
    let instance: AvatarSession<unknown, unknown> | null = null;
    let observer: ResizeObserver | null = null;
    void (async () => {
      const loaded = await format.load();
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
      const state = path ? await readAvatarState(modelPath, path, abort.signal) : instance.readState();
      abort.signal.throwIfAborted();
      await instance.apply(state, "edit", abort.signal);
      if (!abort.signal.aborted) {
        setModule(loaded);
        setSession(instance);
        setValue(instance.readState());
      }
    })().catch((failure) => {
      if (!abort.signal.aborted) {
        observer?.disconnect();
        instance?.dispose();
        instance = null;
        setError(String(failure));
      }
    });
    return () => {
      abort.abort();
      ++request.current;
      observer?.disconnect();
      instance?.dispose();
    };
  }, [format, modelPath, path]);
  const change = (state: unknown) => {
    if (!session || !lifetime.current) return;
    const signal = lifetime.current.signal;
    const sequence = ++request.current;
    setApplying(true);
    void session
      .apply(state, "edit", signal)
      .then(() => {
        if (!signal.aborted && sequence === request.current) {
          setValue(session.readState());
          setError("");
        }
      })
      .catch((failure) => {
        if (!signal.aborted && sequence === request.current) setError(String(failure));
      })
      .finally(() => {
        if (!signal.aborted && sequence === request.current) setApplying(false);
      });
  };
  const save = async () => {
    if (!session || !lifetime.current) return;
    const signal = lifetime.current.signal;
    setPending(true);
    setSaveError("");
    try {
      const result = await saveCharacterModelState({
        name: character.name,
        avatar_type: kind,
        model_path: modelPath,
        sprite_index: index,
        path,
        state: session.readState(),
        tags,
      });
      if (!signal.aborted) onSaved(result);
    } catch (failure) {
      if (!signal.aborted) setSaveError(String(failure));
    } finally {
      if (!signal.aborted) setPending(false);
    }
  };
  const Editor = module?.Editor;
  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!pending}
      closeLabel={t("common.close")}
      title={t(index < 0 ? "character.avatar.newState" : "character.avatar.editState")}
      className="model-state-dialog"
      footer={
        <>
          <Button disabled={pending} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <AsyncButton
            loading={pending}
            disabled={pending || applying || !session || value === null || Boolean(error)}
            onClick={() => void save()}
          >
            {t("character.avatar.saveState")}
          </AsyncButton>
        </>
      }
    >
      <div className="model-state-dialog__layout">
        <div className="model-state-dialog__parameters">
          <label className="field-row field-row--stack">
            <span className="field-row__label">{t("character.sprite.tag")}</span>
            <span className="field-row__control">
              <TextInput
                aria-label={t("character.sprite.tag")}
                value={tags}
                disabled={pending}
                onChange={(event) => setTags(event.target.value)}
              />
            </span>
          </label>
          <fieldset className="model-state-dialog__controls" disabled={pending}>
            {!session && !error && <p role="status">{t("common.loading")}</p>}
            {session && Editor && value !== null && <Editor session={session} value={value} onChange={change} />}
          </fieldset>
          {(error || saveError) && (
            <p className="field-error" role="alert">
              {error || saveError}
            </p>
          )}
        </div>
        <div ref={host} className="model-state-dialog__preview" role="img" aria-label={t("character.avatar.preview")} />
      </div>
    </Dialog>
  );
}
