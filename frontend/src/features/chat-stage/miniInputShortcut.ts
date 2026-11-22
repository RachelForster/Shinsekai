export const DEFAULT_MINI_INPUT_SHORTCUT = "Alt+Q";

const MODIFIER_ORDER = ["Ctrl", "Alt", "Shift", "Super"] as const;
type ShortcutModifier = (typeof MODIFIER_ORDER)[number];

const MODIFIER_ALIASES: Record<string, ShortcutModifier> = {
  ALT: "Alt",
  CMD: "Super",
  CMDORCONTROL: "Ctrl",
  CMDORCTRL: "Ctrl",
  COMMAND: "Super",
  COMMANDORCONTROL: "Ctrl",
  COMMANDORCTRL: "Ctrl",
  CONTROL: "Ctrl",
  CTRL: "Ctrl",
  META: "Super",
  OPTION: "Alt",
  SHIFT: "Shift",
  SUPER: "Super",
  WIN: "Super",
};

const MODIFIER_CODES = new Set([
  "AltLeft",
  "AltRight",
  "ControlLeft",
  "ControlRight",
  "MetaLeft",
  "MetaRight",
  "OSLeft",
  "OSRight",
  "ShiftLeft",
  "ShiftRight",
]);

const MODIFIER_KEYS = new Set(["Alt", "AltGraph", "Control", "Meta", "OS", "Shift", "Super"]);

const CODE_TO_KEY_TOKEN: Record<string, string> = {
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  ArrowUp: "Up",
  Backquote: "Backquote",
  Backslash: "Backslash",
  BracketLeft: "BracketLeft",
  BracketRight: "BracketRight",
  Comma: "Comma",
  End: "End",
  Enter: "Enter",
  Equal: "Equal",
  Home: "Home",
  Insert: "Insert",
  Minus: "Minus",
  NumpadEnter: "Enter",
  PageDown: "PageDown",
  PageUp: "PageUp",
  Period: "Period",
  Quote: "Quote",
  Semicolon: "Semicolon",
  Slash: "Slash",
  Space: "Space",
  Tab: "Tab",
};

const KEY_TOKEN_ALIASES: Record<string, string> = {
  "`": "Backquote",
  "-": "Minus",
  "=": "Equal",
  "[": "BracketLeft",
  "]": "BracketRight",
  "\\": "Backslash",
  ";": "Semicolon",
  "'": "Quote",
  ",": "Comma",
  ".": "Period",
  "/": "Slash",
  " ": "Space",
  ARROWDOWN: "Down",
  ARROWLEFT: "Left",
  ARROWRIGHT: "Right",
  ARROWUP: "Up",
  BACKQUOTE: "Backquote",
  BACKSLASH: "Backslash",
  BRACKETLEFT: "BracketLeft",
  BRACKETRIGHT: "BracketRight",
  COMMA: "Comma",
  DOWN: "Down",
  END: "End",
  ENTER: "Enter",
  EQUAL: "Equal",
  HOME: "Home",
  INSERT: "Insert",
  LEFT: "Left",
  MINUS: "Minus",
  PAGEDOWN: "PageDown",
  PAGEUP: "PageUp",
  PERIOD: "Period",
  QUOTE: "Quote",
  RIGHT: "Right",
  SEMICOLON: "Semicolon",
  SLASH: "Slash",
  SPACE: "Space",
  SPACEBAR: "Space",
  TAB: "Tab",
  UP: "Up",
};

const DISPLAY_KEY_LABELS: Record<string, string> = {
  Backquote: "`",
  Backslash: "\\",
  BracketLeft: "[",
  BracketRight: "]",
  Comma: ",",
  Down: "↓",
  Equal: "=",
  Left: "←",
  Minus: "-",
  Period: ".",
  Quote: "'",
  Right: "→",
  Semicolon: ";",
  Slash: "/",
  Up: "↑",
};

function isFunctionKeyToken(token: string): boolean {
  return /^F(?:[1-9]|1\d|2[0-4])$/.test(token);
}

function normalizeKeyToken(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }
  const upper = trimmed.toUpperCase();
  if (/^[A-Z]$/.test(upper)) {
    return upper;
  }
  if (/^KEY([A-Z])$/.test(upper)) {
    return upper.slice(3);
  }
  if (/^\d$/.test(upper)) {
    return upper;
  }
  if (/^DIGIT(\d)$/.test(upper)) {
    return upper.slice(5);
  }
  if (isFunctionKeyToken(upper)) {
    return upper;
  }
  return KEY_TOKEN_ALIASES[upper] ?? KEY_TOKEN_ALIASES[trimmed] ?? null;
}

function isAllowedShortcutCombination(modifiers: ReadonlySet<ShortcutModifier>, keyToken: string): boolean {
  if (isFunctionKeyToken(keyToken)) {
    // Bare F8 is reserved for hold-to-talk in ChatStage.
    if (keyToken === "F8" && modifiers.size === 0) {
      return false;
    }
    return true;
  }
  return modifiers.has("Ctrl") || modifiers.has("Alt") || modifiers.has("Super");
}

function buildCanonicalShortcut(modifiers: ReadonlySet<ShortcutModifier>, keyToken: string): string | null {
  if (!isAllowedShortcutCombination(modifiers, keyToken)) {
    return null;
  }
  const ordered = MODIFIER_ORDER.filter((modifier) => modifiers.has(modifier));
  return [...ordered, keyToken].join("+");
}

export function normalizeMiniInputShortcut(value: unknown, fallback = DEFAULT_MINI_INPUT_SHORTCUT): string {
  if (typeof value !== "string") {
    return fallback;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  const parts = trimmed.split("+");
  const modifiers = new Set<ShortcutModifier>();
  let keyToken: string | null = null;
  for (const part of parts) {
    const token = part.trim();
    if (!token) {
      return fallback;
    }
    const modifier = MODIFIER_ALIASES[token.toUpperCase()];
    if (modifier) {
      if (keyToken) {
        return fallback;
      }
      modifiers.add(modifier);
      continue;
    }
    if (keyToken) {
      return fallback;
    }
    keyToken = normalizeKeyToken(token);
    if (!keyToken) {
      return fallback;
    }
  }
  if (!keyToken) {
    return fallback;
  }
  return buildCanonicalShortcut(modifiers, keyToken) ?? fallback;
}

function keyTokenFromEvent(event: Pick<KeyboardEvent, "code" | "key">): string | null {
  const code = event.code?.trim() ?? "";
  if (code) {
    if (MODIFIER_CODES.has(code)) {
      return null;
    }
    if (/^Key([A-Z])$/.test(code)) {
      return code.slice(3);
    }
    if (/^Digit(\d)$/.test(code)) {
      return code.slice(5);
    }
    if (isFunctionKeyToken(code.toUpperCase())) {
      return code.toUpperCase();
    }
    if (CODE_TO_KEY_TOKEN[code]) {
      return CODE_TO_KEY_TOKEN[code]!;
    }
  }
  const key = event.key ?? "";
  if (!key || MODIFIER_KEYS.has(key) || key === "Dead" || key === "Process" || key === "Unidentified") {
    return null;
  }
  return normalizeKeyToken(key);
}

export function shortcutFromKeyboardEvent(
  event: Pick<KeyboardEvent, "altKey" | "code" | "ctrlKey" | "key" | "metaKey" | "shiftKey">,
): string | null {
  const keyToken = keyTokenFromEvent(event);
  if (!keyToken) {
    return null;
  }
  const modifiers = new Set<ShortcutModifier>();
  if (event.ctrlKey) {
    modifiers.add("Ctrl");
  }
  if (event.altKey) {
    modifiers.add("Alt");
  }
  if (event.shiftKey) {
    modifiers.add("Shift");
  }
  if (event.metaKey) {
    modifiers.add("Super");
  }
  return buildCanonicalShortcut(modifiers, keyToken);
}

export function matchesMiniInputShortcut(
  event: Pick<KeyboardEvent, "altKey" | "code" | "ctrlKey" | "isComposing" | "key" | "metaKey" | "repeat" | "shiftKey">,
  shortcut: string,
): boolean {
  if (event.repeat || event.isComposing) {
    return false;
  }
  const canonical = normalizeMiniInputShortcut(shortcut, "");
  if (!canonical) {
    return false;
  }
  return shortcutFromKeyboardEvent(event) === canonical;
}

export function formatMiniInputShortcut(shortcut: string): string {
  const canonical = normalizeMiniInputShortcut(shortcut, "");
  if (!canonical) {
    return "";
  }
  return canonical
    .split("+")
    .map((token) => DISPLAY_KEY_LABELS[token] ?? token)
    .join(" + ");
}
