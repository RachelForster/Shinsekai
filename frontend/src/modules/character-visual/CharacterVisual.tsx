import { useEffect, useRef, useState, type MouseEventHandler, type SyntheticEvent } from "react";

import { STATIC_AVATAR_TYPE, type ApplyMode, type AvatarSession, type CharacterVisualAsset } from "./contracts";
import { avatarFormat } from "./registry";
import { avatarAssetUrl, avatarRuntimeAssetUrl } from "./assetUrl";
import { bindAvatarVoice } from "./voiceRoute";
import "./CharacterVisual.css";

export interface CharacterVisualProps {
  asset: CharacterVisualAsset;
  className: string;
  onImageError: (event: SyntheticEvent<HTMLImageElement, Event>) => void;
  onMouseDown: MouseEventHandler<HTMLElement>;
  hitbox: boolean;
  mode: ApplyMode;
  voiceCharacterName?: string;
  stateSequence?: number;
  /** Temporary preview access, never persisted as character data. */
  onReady?: (session: AvatarSession<unknown, unknown> | null) => void;
}

/** The host owns layout; format modules render inside its model container. */
export function CharacterVisual(props: CharacterVisualProps) {
  const { asset, className, onImageError, onMouseDown, hitbox } = props;
  const avatarType = asset.avatarType.trim().toLowerCase() || STATIC_AVATAR_TYPE;
  if (avatarType === STATIC_AVATAR_TYPE) {
    return (
      <img
        alt={asset.label}
        className={className}
        data-chat-stage-hitbox={hitbox ? "true" : undefined}
        onError={onImageError}
        onMouseDown={onMouseDown}
        src={asset.url}
        key={asset.url}
      />
    );
  }
  return <ModelVisual {...props} avatarType={avatarType} key={`${avatarType}:${asset.modelUrl}`} />;
}

function ModelVisual({
  asset,
  avatarType,
  className,
  onMouseDown,
  hitbox,
  mode,
  voiceCharacterName,
  stateSequence,
  onReady,
}: CharacterVisualProps & { avatarType: string }) {
  const format = avatarFormat(avatarType);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [session, setSession] = useState<AvatarSession<unknown, unknown> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (session && voiceCharacterName && mode !== "edit") return bindAvatarVoice(voiceCharacterName, session);
  }, [session, voiceCharacterName, mode]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    if (!format) {
      setError(`unknown avatar format: ${avatarType}`);
      return;
    }
    const controller = new AbortController();
    let created: AvatarSession<unknown, unknown> | null = null;
    let observer: ResizeObserver | null = null;
    setError("");
    setSession(null);
    const create = async () => {
      const module = await format.load();
      if (controller.signal.aborted) return;
      const instance = await module.create(
        {
          element: container,
          modelUrl: asset.modelUrl,
          assetUrl: (path) => avatarAssetUrl(asset.modelUrl, path),
          runtimeAssetUrl: (path) => avatarRuntimeAssetUrl(asset.modelUrl, avatarType, path),
          reportError: (err) => {
            if (!controller.signal.aborted) setError(err.message);
          },
        },
        controller.signal,
      );
      if (controller.signal.aborted) {
        instance.dispose();
        return;
      }
      created = instance;
      const resize = () => instance.resize(container.clientWidth, container.clientHeight);
      resize();
      if (typeof ResizeObserver !== "undefined") {
        observer = new ResizeObserver(resize);
        observer.observe(container);
      }
      setSession(instance);
    };
    void create().catch((err) => {
      if (!controller.signal.aborted) {
        observer?.disconnect();
        created?.dispose();
        created = null;
        setError(err instanceof Error ? err.message : String(err));
      }
    });
    return () => {
      controller.abort();
      observer?.disconnect();
      created?.dispose();
    };
  }, [format, avatarType, asset.modelUrl]);

  useEffect(() => {
    if (!session) return;
    if (!asset.url) {
      onReady?.(session);
      return () => onReady?.(null);
    }
    const controller = new AbortController();
    setError("");
    const apply = async () => {
      const response = await fetch(asset.url, { signal: controller.signal });
      if (!response.ok) throw new Error(`Avatar state request failed: ${response.status}`);
      const state: unknown = await response.json();
      // Some transports cannot abort an already buffered response.
      if (controller.signal.aborted) return;
      await session.apply(state, mode, controller.signal);
      if (!controller.signal.aborted) onReady?.(session);
    };
    void apply().catch((err) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
    });
    return () => {
      controller.abort();
      onReady?.(null);
    };
  }, [session, asset.url, mode, stateSequence, onReady]);

  return (
    <div
      className={`${className} character-visual__model`}
      data-avatar-type={avatarType}
      data-chat-stage-hitbox={hitbox ? "true" : undefined}
      onMouseDown={onMouseDown}
      aria-label={asset.label}
    >
      <div ref={containerRef} className="character-visual__viewport" data-testid="model-container" />
      {error ? (
        <div className="character-visual__error" role="status">
          {error}
        </div>
      ) : null}
    </div>
  );
}
