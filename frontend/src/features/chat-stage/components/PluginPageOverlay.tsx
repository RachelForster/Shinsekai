import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";

import type { PluginPageTarget } from "../../../shared/plugin/PluginSlot";
import "./PluginPageOverlay.css";

const WIDTH = 336;
const HEIGHT = 680;

type Pos = { x: number; y: number };

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(min, value), Math.max(min, max));

// Build the plugin page URL the same way the bridge does (plugin_ui._frontend_page_payload),
// resolve it against the bridge base if the app runs behind one, and forward the bridge token
// so the page's RPC calls authenticate.
function pluginPageSrc(pluginId: string, pageId: string, nonce: number): string {
  const path =
    `/api/plugins/${encodeURIComponent(pluginId)}/frontend/${encodeURIComponent(pageId)}/` +
    `?pluginId=${encodeURIComponent(pluginId)}&pageId=${encodeURIComponent(pageId)}&_n=${nonce}`;
  if (typeof window === "undefined") {
    return path;
  }
  const params = new URLSearchParams(window.location.search);
  const bridgeBase = params.get("shinsekai_bridge")?.trim();
  const token = params.get("shinsekai_bridge_token")?.trim();
  let url = path;
  if (bridgeBase) {
    try {
      url = new URL(path, bridgeBase).toString();
    } catch {
      url = path;
    }
  }
  if (token) {
    url += `${url.includes("?") ? "&" : "?"}shinsekai_bridge_token=${encodeURIComponent(token)}`;
  }
  return url;
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
  const [nonce] = useState(() => Date.now());
  const [pos, setPos] = useState<Pos>(() => ({
    x: clamp(window.innerWidth - WIDTH - 24, 8, Math.max(8, window.innerWidth - WIDTH - 8)),
    y: 84,
  }));
  const posRef = useRef(pos);
  posRef.current = pos;
  const dragBase = useRef<Pos | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);

  // Host-owned drag surface: the bottom bar. A press that never moves is a tap → close.
  const onBarPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0) {
      return;
    }
    dragBase.current = posRef.current;
    const startX = event.screenX;
    const startY = event.screenY;
    let moved = false;
    const move = (e: PointerEvent) => {
      if (!dragBase.current) {
        return;
      }
      const dx = e.screenX - startX;
      const dy = e.screenY - startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        moved = true;
      }
      setPos({
        x: clamp(dragBase.current.x + dx, 8, window.innerWidth - WIDTH - 8),
        y: clamp(dragBase.current.y + dy, 8, window.innerHeight - 56),
      });
    };
    const up = () => {
      dragBase.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (!moved) {
        onClose();
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // Optional drag from inside a cooperating iframe page (press any blank area), streamed
  // via postMessage as absolute screen-coordinate deltas so moving the window stays exact.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frame = frameRef.current;
      if (frame && event.source !== frame.contentWindow) {
        return;
      }
      const d = event.data as { __pluginOverlay?: string; dx?: number; dy?: number; type?: string } | null;
      if (!d || d.__pluginOverlay !== "drag") {
        return;
      }
      if (d.type === "start") {
        dragBase.current = posRef.current;
      } else if (d.type === "move" && dragBase.current) {
        setPos({
          x: clamp(dragBase.current.x + (d.dx ?? 0), 8, window.innerWidth - WIDTH - 8),
          y: clamp(dragBase.current.y + (d.dy ?? 0), 8, window.innerHeight - 56),
        });
      } else if (d.type === "end") {
        dragBase.current = null;
      } else if (d.type === "close") {
        onClose();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [onClose]);

  return createPortal(
    <div
      className="plugin-overlay"
      data-chat-stage-hitbox="true"
      style={{ height: HEIGHT, left: pos.x, top: pos.y, width: WIDTH }}
    >
      <iframe
        className="plugin-overlay__frame"
        ref={frameRef}
        sandbox="allow-forms allow-same-origin allow-scripts"
        src={pluginPageSrc(target.pluginId, target.pageId, nonce)}
        title="Plugin"
      />
      <button aria-label="Collapse" className="plugin-overlay__bar" onPointerDown={onBarPointerDown} type="button">
        <span aria-hidden className="plugin-overlay__grip" />
      </button>
    </div>,
    document.body,
  );
}
