import { useEffect, useRef, useState, type MouseEvent, type PointerEvent, type RefObject } from "react";

interface DragSelection {
  pointer: number;
  anchor: string;
  before: ReadonlySet<string>;
  x: number;
  startY: number;
  y: number;
  last: string;
  frame: number;
}

function messageRows(body: HTMLElement) {
  return Array.from(body.querySelectorAll<HTMLElement>("[data-history-entry-id]"));
}

export function useHistorySelection(ids: string[], bodyRef: RefObject<HTMLDivElement>) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const [anchor, setAnchor] = useState<string>();
  const drag = useRef<DragSelection>();
  const suppressClick = useRef(false);

  const stopDrag = () => {
    if (drag.current) cancelAnimationFrame(drag.current.frame);
    drag.current = undefined;
  };
  useEffect(() => stopDrag, []);

  const selectRange = (start: string, end: string, before: ReadonlySet<string>) => {
    const first = ids.indexOf(start);
    const last = ids.indexOf(end);
    if (first < 0 || last < 0) return;
    const range = ids.slice(Math.min(first, last), Math.max(first, last) + 1);
    setSelected(new Set([...before, ...range]));
    setAnchor(start);
  };
  const reset = (next: string[] = [], start = next[0]) => {
    stopDrag();
    setSelected(new Set(next));
    setAnchor(start);
  };
  const click = (event: MouseEvent, id: string) => {
    if (event.detail && suppressClick.current) return;
    if (event.shiftKey && anchor) {
      selectRange(anchor, id, selected);
      return;
    }
    const next = new Set(selected);
    if (next.delete(id)) {
      if (id === anchor) setAnchor(Array.from(next).at(-1));
    } else {
      next.add(id);
      setAnchor(id);
    }
    setSelected(next);
  };
  const selectToVisibleEnd = () => {
    const body = bodyRef.current;
    if (!body || !anchor) return;
    const { top, bottom } = body.getBoundingClientRect();
    const end = messageRows(body)
      .reverse()
      .find((row) => {
        const rect = row.getBoundingClientRect();
        return rect.top < bottom - 12 && rect.bottom > top;
      })?.dataset.historyEntryId;
    if (end) selectRange(anchor, end, selected);
  };

  const updateDrag = (gesture: DragSelection) => {
    gesture.frame = 0;
    const body = bodyRef.current;
    if (!body || drag.current !== gesture) return;
    const { top, bottom } = body.getBoundingClientRect();
    const edge = 42;
    const overTop = top + edge - gesture.y;
    const overBottom = gesture.y - bottom + edge;
    const previousScroll = body.scrollTop;
    if (overTop > 0 || overBottom > 0) {
      body.scrollTop += Math.max(-24, Math.min(24, (overBottom > 0 ? overBottom : -overTop) / 3));
    }
    const y = Math.min(bottom - 3, Math.max(top + 3, gesture.y));
    const rows = messageRows(body);
    const end = (rows.find((row) => y <= row.getBoundingClientRect().bottom + 5) ?? rows.at(-1))?.dataset
      .historyEntryId;
    if (end && gesture.last !== end) {
      gesture.last = end;
      selectRange(gesture.anchor, end, gesture.before);
    }
    if (body.scrollTop !== previousScroll) gesture.frame = requestAnimationFrame(() => updateDrag(gesture));
  };

  return {
    selected,
    anchor,
    reset,
    click,
    selectToVisibleEnd,
    pointerHandlers: {
      onPointerDown(event: PointerEvent<HTMLDivElement>) {
        suppressClick.current = false;
        if (!event.isPrimary || event.pointerType === "touch" || event.button !== 0 || event.shiftKey) return;
        const id = (event.target as HTMLElement).closest<HTMLElement>("[data-history-entry-id]")?.dataset
          .historyEntryId;
        if (!id) return;
        stopDrag();
        drag.current = {
          pointer: event.pointerId,
          anchor: id,
          before: selected,
          x: event.clientX,
          startY: event.clientY,
          y: event.clientY,
          last: "",
          frame: 0,
        };
      },
      onPointerMove(event: PointerEvent<HTMLDivElement>) {
        const gesture = drag.current;
        if (!gesture || event.pointerId !== gesture.pointer) return;
        if (!event.buttons) {
          stopDrag();
          return;
        }
        gesture.y = event.clientY;
        if (!suppressClick.current) {
          if (Math.hypot(event.clientX - gesture.x, gesture.y - gesture.startY) < 6) return;
          suppressClick.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
        }
        if (!gesture.frame) updateDrag(gesture);
      },
      onPointerUp: stopDrag,
      onPointerCancel: stopDrag,
      onLostPointerCapture: stopDrag,
    },
  };
}
