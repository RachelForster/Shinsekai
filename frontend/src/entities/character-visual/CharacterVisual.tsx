import { useEffect, useRef, useState, type MouseEventHandler, type SyntheticEvent } from "react";

import { STATIC_AVATAR_TYPE, type AvatarSession, type CharacterVisualAsset } from "./contracts";
import { avatarFormat } from "./registry";

export interface CharacterVisualProps {
  asset: CharacterVisualAsset;
  imageClassName?: string;
  imageOnError?: (event: SyntheticEvent<HTMLImageElement, Event>) => void;
  imageOnMouseDown?: MouseEventHandler<HTMLElement>;
  hitbox?: boolean;
}

/** 唯一的形象分发点：static 渲染现有 img，模型格式按注册表挂载。 */
export function CharacterVisual({
  asset,
  imageClassName,
  imageOnError,
  imageOnMouseDown,
  hitbox,
}: CharacterVisualProps) {
  const avatarType = asset.avatarType?.trim() || STATIC_AVATAR_TYPE;
  if (avatarType === STATIC_AVATAR_TYPE) {
    return (
      <img
        alt={asset.label}
        className={imageClassName}
        data-chat-stage-hitbox={hitbox ? "true" : undefined}
        onError={imageOnError}
        onMouseDown={imageOnMouseDown}
        src={asset.url}
      />
    );
  }
  return <ModelVisual asset={asset} avatarType={avatarType} />;
}

function ModelVisual({ asset, avatarType }: { asset: CharacterVisualAsset; avatarType: string }) {
  const format = avatarFormat(avatarType);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!format) {
      setError(`unknown avatar format: ${avatarType}`);
      return;
    }
    const container = containerRef.current;
    if (!container) {
      return;
    }

    let cancelled = false;
    let session: AvatarSession<unknown, unknown> | null = null;
    const controller = new AbortController();

    format
      .load()
      .then((module) =>
        module.create(
          {
            element: container,
            modelUrl: asset.modelUrl ?? "",
            assetUrl: (relativePath) => relativePath,
            reportError: (err) => {
              if (!cancelled) {
                setError(err.message);
              }
            },
          },
          controller.signal,
        ),
      )
      .then(async (created) => {
        if (cancelled) {
          created.dispose();
          return;
        }
        session = created;
        session.resize(container.clientWidth, container.clientHeight);
        if (asset.url) {
          try {
            const response = await fetch(asset.url, { signal: controller.signal });
            const state = await response.json();
            await session.apply(state, "play", controller.signal);
          } catch (err) {
            if (cancelled || (err instanceof DOMException && err.name === "AbortError")) {
              return;
            }
            setError(err instanceof Error ? err.message : String(err));
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => {
        session?.resize(container.clientWidth, container.clientHeight);
      });
      observer.observe(container);
    }

    return () => {
      cancelled = true;
      controller.abort();
      observer?.disconnect();
      session?.dispose();
      session = null;
    };
  }, [format, avatarType, asset.modelUrl, asset.url]);

  if (error) {
    return (
      <div className="character-visual__error" data-avatar-type={avatarType} role="status">
        {error}
      </div>
    );
  }
  return (
    <div
      ref={containerRef}
      className="character-visual__model"
      data-avatar-type={avatarType}
      data-testid="model-container"
    />
  );
}
