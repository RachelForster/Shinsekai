import type { CSSProperties, KeyboardEvent } from "react";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { DEFAULT_CHARACTER_COLOR } from "../constants";
import { useI18n } from "../i18n";
import {
  filterMentionOptions,
  insertMention,
  mentionQueryAt,
  readRecentMentionIds,
  rememberRecentMentionId,
  resolveMentionCaret,
  scrollChildIntoContainer,
  sortMentionOptions,
  splitMentionSegments,
  writeRecentMentionIds,
  type MentionOption,
  type MentionQuery,
} from "./mentionTokens";
import "./CustomSelect.css";
import "./MentionTextArea.css";

interface MentionTextAreaProps {
  "aria-label"?: string;
  className?: string;
  disabled?: boolean;
  maxLength?: number;
  onChange: (value: string) => void;
  options: MentionOption[];
  placeholder?: string;
  rows?: number;
  value: string;
}

const CARET_MIRROR_STYLES = [
  "direction",
  "boxSizing",
  "width",
  "height",
  "overflowX",
  "overflowY",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "borderStyle",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "fontStyle",
  "fontVariant",
  "fontWeight",
  "fontStretch",
  "fontSize",
  "lineHeight",
  "fontFamily",
  "textAlign",
  "textTransform",
  "textIndent",
  "textDecoration",
  "letterSpacing",
  "wordSpacing",
] as const;

function clamp(value: number, min: number, max: number) {
  if (max < min) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function textareaIndexViewportRect(textarea: HTMLTextAreaElement, index: number) {
  const computed = window.getComputedStyle(textarea);
  const mirror = document.createElement("div");
  const style = mirror.style;
  style.position = "absolute";
  style.visibility = "hidden";
  style.whiteSpace = "pre-wrap";
  style.wordWrap = "break-word";
  style.overflow = "hidden";
  style.top = "0";
  style.left = "-9999px";
  for (const property of CARET_MIRROR_STYLES) {
    style[property] = computed[property];
  }
  style.width = `${textarea.clientWidth}px`;
  const safeIndex = Math.max(0, Math.min(index, textarea.value.length));
  mirror.textContent = textarea.value.slice(0, safeIndex);
  const marker = document.createElement("span");
  marker.textContent = textarea.value.slice(safeIndex) || ".";
  mirror.appendChild(marker);
  document.body.appendChild(mirror);
  const textareaRect = textarea.getBoundingClientRect();
  const borderTop = Number.parseFloat(computed.borderTopWidth) || 0;
  const borderLeft = Number.parseFloat(computed.borderLeftWidth) || 0;
  const lineHeight = Number.parseFloat(computed.lineHeight) || marker.offsetHeight || 20;
  const top = textareaRect.top + marker.offsetTop + borderTop - textarea.scrollTop;
  const left = textareaRect.left + marker.offsetLeft + borderLeft - textarea.scrollLeft;
  mirror.remove();
  return { height: lineHeight, left, top };
}

export function MentionTextArea({
  "aria-label": ariaLabel,
  className = "",
  disabled,
  maxLength,
  onChange,
  options,
  placeholder,
  rows = 6,
  value,
}: MentionTextAreaProps) {
  const { t } = useI18n();
  const listId = useId();
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const pendingCaretRef = useRef<number | null>(null);
  const applyingCaretRef = useRef(false);
  const [mention, setMention] = useState<MentionQuery | null>(null);
  const [highlighted, setHighlighted] = useState(0);
  const [recentIds, setRecentIds] = useState(readRecentMentionIds);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>();
  const rankedOptions = useMemo(() => sortMentionOptions(options, recentIds), [options, recentIds]);
  const matches = useMemo(
    () => (mention ? filterMentionOptions(rankedOptions, mention.query) : []),
    [mention, rankedOptions],
  );
  const segments = useMemo(() => splitMentionSegments(value, options), [options, value]);
  const popupOpen = Boolean(mention) && !disabled;
  const highlightedIndex = matches.length ? Math.min(highlighted, matches.length - 1) : 0;

  const syncMentionFromArea = (area: HTMLTextAreaElement) => {
    if (applyingCaretRef.current) {
      return;
    }
    const caret = resolveMentionCaret(area.value, area.selectionStart ?? area.value.length);
    setMention(mentionQueryAt(area.value, caret));
  };

  const pick = (option: MentionOption) => {
    const area = areaRef.current;
    if (!mention || !area) {
      return;
    }
    const caret = resolveMentionCaret(area.value, area.selectionStart ?? area.value.length);
    const next = insertMention(area.value, caret, option, mention.start);
    const nextRecent = rememberRecentMentionId(recentIds, option.id);
    setRecentIds(nextRecent);
    writeRecentMentionIds(nextRecent);
    pendingCaretRef.current = next.caret;
    onChange(next.value);
    setMention(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!popupOpen || !matches.length) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((current) => Math.min(matches.length - 1, current + 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((current) => Math.max(0, current - 1));
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      const option = matches[highlightedIndex] ?? matches[0];
      if (option) {
        pick(option);
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setMention(null);
    }
  };

  const updateMenuPosition = useCallback(() => {
    const area = areaRef.current;
    if (!area || !mention) {
      return;
    }
    const caret = textareaIndexViewportRect(area, mention.start);
    const visualViewport = window.visualViewport;
    const viewportLeft = visualViewport?.offsetLeft ?? 0;
    const viewportTop = visualViewport?.offsetTop ?? 0;
    const viewportWidth = visualViewport?.width ?? window.innerWidth;
    const viewportHeight = visualViewport?.height ?? window.innerHeight;
    const padding = 12;
    const gap = 6;
    const minLeft = viewportLeft + padding;
    const minTop = viewportTop + padding;
    const maxRight = viewportLeft + viewportWidth - padding;
    const maxBottom = viewportTop + viewportHeight - padding;
    const menuWidth = Math.min(240, Math.max(160, maxRight - minLeft));
    const measuredHeight = menuRef.current?.getBoundingClientRect().height;
    const estimatedHeight = Math.min(260, Math.max(44, matches.length * 36 + 10));
    const menuHeight = measuredHeight && measuredHeight > 0 ? measuredHeight : estimatedHeight;
    const preferredTop = caret.top - menuHeight - gap;
    const openAbove = preferredTop >= minTop;
    const top = clamp(openAbove ? preferredTop : caret.top + caret.height + gap, minTop, maxBottom - menuHeight);
    const left = clamp(caret.left, minLeft, maxRight - menuWidth);
    setMenuStyle({
      left,
      maxHeight: 260,
      minWidth: 160,
      top,
      width: menuWidth,
    });
  }, [matches.length, mention]);

  useEffect(() => {
    setHighlighted(0);
  }, [mention?.query, mention?.start]);

  useLayoutEffect(() => {
    const caret = pendingCaretRef.current;
    const area = areaRef.current;
    if (caret == null || !area) {
      return;
    }
    applyingCaretRef.current = true;
    area.focus();
    area.setSelectionRange(caret, caret);
    applyingCaretRef.current = false;
    pendingCaretRef.current = null;
  }, [value]);

  useLayoutEffect(() => {
    if (!popupOpen) {
      return;
    }
    updateMenuPosition();
  }, [popupOpen, updateMenuPosition]);

  useLayoutEffect(() => {
    if (!popupOpen) {
      return;
    }
    const menu = menuRef.current;
    const active = menu?.querySelector<HTMLElement>("[data-active='true']");
    if (menu && active) {
      scrollChildIntoContainer(menu, active);
    }
  }, [highlightedIndex, popupOpen]);

  useEffect(() => {
    if (!popupOpen) {
      return;
    }
    const visualViewport = window.visualViewport;
    const handleReposition = () => updateMenuPosition();
    const handlePointerDown = (event: PointerEvent) => {
      const node = event.target as Node;
      if (areaRef.current?.contains(node) || menuRef.current?.contains(node)) {
        return;
      }
      setMention(null);
    };
    window.addEventListener("resize", handleReposition);
    window.addEventListener("scroll", handleReposition, true);
    visualViewport?.addEventListener("resize", handleReposition);
    visualViewport?.addEventListener("scroll", handleReposition);
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      window.removeEventListener("resize", handleReposition);
      window.removeEventListener("scroll", handleReposition, true);
      visualViewport?.removeEventListener("resize", handleReposition);
      visualViewport?.removeEventListener("scroll", handleReposition);
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [popupOpen, updateMenuPosition]);

  return (
    <div className={["mention-editor", "textarea", disabled ? "is-disabled" : "", className].filter(Boolean).join(" ")}>
      <div aria-hidden className="mention-editor__mirror" ref={mirrorRef}>
        {segments.map((segment, index) =>
          segment.type === "mention" && segment.option ? (
            <span
              className="mention-editor__chip"
              key={`${segment.option.id}-${index}`}
              style={{ "--mention-color": segment.option.color?.trim() || DEFAULT_CHARACTER_COLOR } as CSSProperties}
            >
              {segment.value}
            </span>
          ) : (
            <span key={`text-${index}`}>{segment.value}</span>
          ),
        )}
      </div>
      <textarea
        aria-activedescendant={popupOpen ? `${listId}-option-${highlightedIndex}` : undefined}
        aria-autocomplete="list"
        aria-controls={popupOpen ? listId : undefined}
        aria-expanded={popupOpen}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        className="mention-editor__input"
        disabled={disabled}
        maxLength={maxLength}
        onChange={(event) => {
          pendingCaretRef.current = null;
          onChange(event.target.value);
          syncMentionFromArea(event.target);
        }}
        onClick={(event) => syncMentionFromArea(event.currentTarget)}
        onKeyDown={onKeyDown}
        onKeyUp={(event) => syncMentionFromArea(event.currentTarget)}
        onScroll={(event) => {
          if (mirrorRef.current) {
            mirrorRef.current.scrollTop = event.currentTarget.scrollTop;
            mirrorRef.current.scrollLeft = event.currentTarget.scrollLeft;
          }
          if (popupOpen) {
            updateMenuPosition();
          }
        }}
        onSelect={(event) => syncMentionFromArea(event.currentTarget)}
        placeholder={placeholder}
        ref={areaRef}
        rows={rows}
        value={value}
      />
      {popupOpen
        ? createPortal(
            <div
              aria-label={t("mention.listLabel")}
              className="custom-select__menu"
              id={listId}
              ref={menuRef}
              role="listbox"
              style={menuStyle}
            >
              {matches.length ? (
                matches.map((option, index) => (
                  <button
                    aria-selected={index === highlightedIndex}
                    className="custom-select__option"
                    data-active={index === highlightedIndex || undefined}
                    id={`${listId}-option-${index}`}
                    key={option.id}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      pick(option);
                    }}
                    role="option"
                    tabIndex={-1}
                    type="button"
                  >
                    <span className="custom-select__option-label">{option.label}</span>
                  </button>
                ))
              ) : (
                <div className="mention-editor__empty">{t("mention.empty")}</div>
              )}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

export { characterMentionOptions, type MentionOption } from "./mentionTokens";
