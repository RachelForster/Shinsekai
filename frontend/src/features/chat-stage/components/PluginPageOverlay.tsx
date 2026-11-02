import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";

import { getPluginUiDetail } from "../../../entities/plugin/repository";
import { useI18n } from "../../../shared/i18n";
import { resolvePlatformHttpUrl } from "../../../shared/platform/platform";
import type { PluginPageTarget } from "../../../shared/plugin/PluginSlot";
import "./PluginPageOverlay.css";

const DEFAULT_WIDTH = 360;
const DEFAULT_HEIGHT = 640;
const VIEWPORT_MARGIN = 8;

type Pos = { x: number; y: number };
type Size = { height: number; width: number };
type PointerDrag = {
  moved: boolean;
  origin: Pos;
  pointerId: number;
  startX: number;
  startY: number;
};
type OverlayPage = { src: string; title: string };

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(min, value), Math.max(min, max));

function viewportSize(): Size {
  return {
    height: Math.max(1, Math.min(DEFAULT_HEIGHT, window.innerHeight - VIEWPORT_MARGIN * 2)),
    width: Math.max(1, Math.min(DEFAULT_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2)),
  };
}

function clampPosition(pos: Pos, size: Size): Pos {
  return {
    x: clamp(pos.x, VIEWPORT_MARGIN, window.innerWidth - size.width - VIEWPORT_MARGIN),
    y: clamp(pos.y, VIEWPORT_MARGIN, window.innerHeight - size.height - VIEWPORT_MARGIN),
  };
}

function initialPosition(size: Size): Pos {
  return clampPosition(
    {
      x: window.innerWidth - size.width - 24,
      y: 84,
    },
    size,
  );
}

/**
 * A floating, draggable window that hosts a plugin's frontend page over the chat
 * stage. Opened when a chat-UI-slot contribution declares pageMode "overlay"
 * (see FrontendChatUIContribution). Drag it by the bottom bar, or — for a
 * cooperating page — from any blank area inside it (the page streams
 * `{ __pluginOverlay: "drag", type, dx, dy }` messages using absolute screen
 * coordinates). Tapping the bottom bar (a press with no drag) collapses it.
 */
export function PluginPageOverlay({ onClose, target }: { onClose: () => void; target: PluginPageTarget }) {
  const { t } = useI18n();
  const [size, setSize] = useState<Size>(viewportSize);
  const [pos, setPos] = useState<Pos>(() => initialPosition(viewportSize()));
  const [page, setPage] = useState<OverlayPage | null>(null);
  const [pageError, setPageError] = useState(false);
  const posRef = useRef(pos);
  posRef.current = pos;
  const dragBase = useRef<Pos | null>(null);
  const pointerDragRef = useRef<PointerDrag | null>(null);
  const suppressClickRef = useRef(false);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const frameLoadedRef = useRef(false);

  useEffect(() => {
    let active = true;
    frameLoadedRef.current = false;
    setPage(null);
    setPageError(false);
    void getPluginUiDetail(target.pluginId)
      .then((detail) => {
        if (!active) {
          return;
        }
        const matchedPage = detail.pages.find(
          (item) => item.id === target.pageId && item.pluginId === target.pluginId && item.frontendUrl,
        );
        if (!matchedPage?.frontendUrl) {
          setPageError(true);
          return;
        }
        setPage({
          src: resolvePlatformHttpUrl(matchedPage.frontendUrl),
          title: matchedPage.title || target.pageId,
        });
      })
      .catch(() => {
        if (active) {
          setPageError(true);
        }
      });
    return () => {
      active = false;
    };
  }, [target.pageId, target.pluginId]);

  const postPresentation = useCallback(() => {
    const frameWindow = frameRef.current?.contentWindow;
    if (!frameWindow || !page || !target.presentationId) {
      return;
    }
    try {
      const targetOrigin = new URL(page.src, window.location.href).origin;
      frameWindow.postMessage(
        {
          __shinsekai: "plugin-page",
          payload: target.payload ?? {},
          presentationId: target.presentationId,
          type: "present",
        },
        targetOrigin,
      );
    } catch {
      // A malformed page URL is handled by the iframe load/error state.
    }
  }, [page, target.payload, target.presentationId]);

  useEffect(() => {
    if (frameLoadedRef.current) {
      postPresentation();
    }
  }, [postPresentation]);

  useEffect(() => {
    const handleResize = () => {
      const nextSize = viewportSize();
      setSize(nextSize);
      setPos((current) => clampPosition(current, nextSize));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const onBarPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    pointerDragRef.current = {
      moved: false,
      origin: posRef.current,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
    };
  };

  const onBarPointerMove = (event: ReactPointerEvent) => {
    const drag = pointerDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
      drag.moved = true;
    }
    setPos(clampPosition({ x: drag.origin.x + dx, y: drag.origin.y + dy }, size));
  };

  const finishBarPointerDrag = (event: ReactPointerEvent) => {
    const drag = pointerDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    suppressClickRef.current = drag.moved;
    pointerDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onBarClick = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onClose();
  };

  // Optional drag from inside a cooperating iframe page (press any blank area), streamed
  // via postMessage as absolute screen-coordinate deltas so moving the window stays exact.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frame = frameRef.current;
      if (!frame || event.source !== frame.contentWindow) {
        return;
      }
      const d = event.data as { __pluginOverlay?: string; dx?: number; dy?: number; type?: string } | null;
      if (!d || d.__pluginOverlay !== "drag") {
        return;
      }
      if (d.type === "start") {
        dragBase.current = posRef.current;
      } else if (d.type === "move" && dragBase.current) {
        const dx = Number.isFinite(d.dx) ? (d.dx ?? 0) : 0;
        const dy = Number.isFinite(d.dy) ? (d.dy ?? 0) : 0;
        setPos(
          clampPosition(
            {
              x: dragBase.current.x + dx,
              y: dragBase.current.y + dy,
            },
            size,
          ),
        );
      } else if (d.type === "end") {
        dragBase.current = null;
      } else if (d.type === "close") {
        onClose();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [onClose, size]);

  return createPortal(
    <section
      aria-label={page?.title || target.pageId}
      className="plugin-overlay"
      data-chat-stage-hitbox="true"
      data-plugin-page-overlay="true"
      role="dialog"
      style={{ height: size.height, left: pos.x, top: pos.y, width: size.width }}
    >
      {page ? (
        <iframe
          className="plugin-overlay__frame"
          ref={frameRef}
          sandbox="allow-forms allow-same-origin allow-scripts"
          src={page.src}
          title={page.title}
          onLoad={() => {
            frameLoadedRef.current = true;
            postPresentation();
          }}
        />
      ) : (
        <div className="plugin-overlay__status" role={pageError ? "alert" : "status"}>
          {t(pageError ? "plugin.loadError.unavailable" : "plugin.detail.loading")}
        </div>
      )}
      <button
        aria-label={t("common.close")}
        className="plugin-overlay__bar"
        onClick={onBarClick}
        onPointerCancel={finishBarPointerDrag}
        onPointerDown={onBarPointerDown}
        onPointerMove={onBarPointerMove}
        onPointerUp={finishBarPointerDrag}
        type="button"
      >
        <span aria-hidden className="plugin-overlay__grip" />
      </button>
    </section>,
    document.body,
  );
}
