import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type Ref } from "react";
import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";

type Position = [number, number];
const initialView = { zoom: 1, pan: [0, 0] as Position };

function boundedPan([x, y]: Position, zoom: number, { width, height }: DOMRect): Position {
  const maxX = (width * (zoom - 1)) / 2;
  const maxY = (height * (zoom - 1)) / 2;
  return [Math.max(-maxX, Math.min(maxX, x)), Math.max(-maxY, Math.min(maxY, y))];
}

function zoomView(view: typeof initialView, factor: number, bounds: DOMRect, [x, y]: Position) {
  const zoom = Math.max(1, Math.min(8, view.zoom * factor));
  if (zoom === view.zoom) return view;
  const scale = zoom / view.zoom;
  const pan = boundedPan([x - (x - view.pan[0]) * scale, y - (y - view.pan[1]) * scale], zoom, bounds);
  return { zoom, pan };
}

export function SpriteMouthCanvas({
  size,
  focus,
  contentRef,
  children,
}: {
  size: [number, number];
  focus: [number, number];
  contentRef: Ref<HTMLDivElement>;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const viewport = useRef<HTMLDivElement>(null);
  const [{ zoom, pan }, setView] = useState(initialView);
  const drag = useRef<{ x: number; y: number; pan: Position } | null>(null);
  useEffect(() => {
    const canvas = viewport.current;
    if (!canvas) return;
    const wheel = (event: WheelEvent) => {
      if (!event.deltaY || drag.current) return;
      event.preventDefault();
      const bounds = canvas.getBoundingClientRect();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1;
      const anchor: Position = [
        event.clientX - bounds.left - bounds.width / 2,
        event.clientY - bounds.top - bounds.height / 2,
      ];
      setView((view) => zoomView(view, Math.exp((-event.deltaY * unit) / 250), bounds, anchor));
    };
    canvas.addEventListener("wheel", wheel, { passive: false });
    return () => canvas.removeEventListener("wheel", wheel);
  }, []);
  const changeZoom = (factor: number) => {
    const bounds = viewport.current?.getBoundingClientRect();
    if (!bounds) return;
    setView((view) =>
      zoomView(view, factor, bounds, [
        view.pan[0] + (focus[0] - 0.5) * bounds.width * view.zoom,
        view.pan[1] + (focus[1] - 0.5) * bounds.height * view.zoom,
      ]),
    );
  };
  return (
    <div className="sprite-mouth-editor__canvas-shell" style={{ "--mouth-aspect": size[0] / size[1] } as CSSProperties}>
      <div
        ref={viewport}
        className="sprite-mouth-editor__viewport"
        data-zoom={zoom}
        style={{ aspectRatio: size[0] / size[1], cursor: zoom > 1 ? "grab" : "default" }}
        onPointerDown={(event) => {
          if (event.button !== 0 || zoom <= 1 || (event.target as Element).closest("button,input,select,video")) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = { x: event.clientX, y: event.clientY, pan };
        }}
        onPointerMove={(event) => {
          const start = drag.current;
          if (!start) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          const position: Position = [start.pan[0] + event.clientX - start.x, start.pan[1] + event.clientY - start.y];
          setView((view) => ({ ...view, pan: boundedPan(position, view.zoom, bounds) }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <div
          ref={contentRef}
          className="sprite-mouth-editor__plane"
          style={
            { transform: `translate(${pan[0]}px, ${pan[1]}px) scale(${zoom})`, "--mouth-zoom": zoom } as CSSProperties
          }
        >
          {children}
        </div>
      </div>
      <div className="sprite-mouth-editor__zoom" role="group" aria-label={t("spriteMouth.canvasZoom")}>
        <Button aria-label={t("spriteMouth.zoomOut")} disabled={zoom <= 1} onClick={() => changeZoom(1 / 1.5)}>
          <ZoomOut size={17} aria-hidden />
        </Button>
        <Button aria-label={t("spriteMouth.resetView")} onClick={() => setView(initialView)}>
          {Math.round(zoom * 100)}% <RotateCcw size={12} aria-hidden />
        </Button>
        <Button aria-label={t("spriteMouth.zoomIn")} disabled={zoom >= 8} onClick={() => changeZoom(1.5)}>
          <ZoomIn size={17} aria-hidden />
        </Button>
      </div>
    </div>
  );
}
