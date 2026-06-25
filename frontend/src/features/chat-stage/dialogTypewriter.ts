import { parseHtmlFragment, stripHtmlFallback } from "./htmlFragment";
import { markdownToDialogHtml } from "./markdownRenderer";

const typewriterCacheMaxEntries = 96;

function refreshCacheEntry<Key, Value>(cache: Map<Key, Value>, key: Key, value: Value) {
  if (cache.has(key)) {
    cache.delete(key);
  }
  cache.set(key, value);
  while (cache.size > typewriterCacheMaxEntries) {
    const oldest = cache.keys().next();
    if (oldest.done) {
      break;
    }
    cache.delete(oldest.value);
  }
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function codepoints(value: string) {
  return Array.from(value ?? "");
}

function sliceCodepoints(value: string, count: number) {
  return codepoints(value).slice(0, Math.max(0, count)).join("");
}

function isLineBreakCharacter(value: string) {
  return value === "\n" || value === "\r";
}

function isInlineWhitespace(value: string) {
  return value !== "\n" && value !== "\r" && /\s/u.test(value);
}

function isWordCharacter(value: string) {
  return /[\p{Script=Latin}\p{N}_'’-]/u.test(value);
}

interface DirectionalToken {
  text: string;
  visible: boolean;
}

function directionalLineTokens(value: string) {
  const chars = codepoints(value);
  const tokens: DirectionalToken[] = [];
  let index = 0;
  while (index < chars.length) {
    const char = chars[index] ?? "";
    if (isInlineWhitespace(char)) {
      let text = char;
      index += 1;
      while (index < chars.length && isInlineWhitespace(chars[index] ?? "")) {
        text += chars[index] ?? "";
        index += 1;
      }
      tokens.push({ text, visible: false });
      continue;
    }
    if (isWordCharacter(char)) {
      let text = char;
      index += 1;
      while (index < chars.length && isWordCharacter(chars[index] ?? "")) {
        text += chars[index] ?? "";
        index += 1;
      }
      tokens.push({ text, visible: true });
      continue;
    }
    tokens.push({ text: char, visible: true });
    index += 1;
  }
  return tokens;
}

function directionalTextTokens(value: string, reverseLines: boolean) {
  const tokens: DirectionalToken[] = [];
  const chars = codepoints(value);
  let line = "";
  const flushLine = () => {
    const lineTokens = directionalLineTokens(line);
    tokens.push(...(reverseLines ? lineTokens.reverse() : lineTokens));
    line = "";
  };
  for (const char of chars) {
    if (isLineBreakCharacter(char)) {
      flushLine();
      tokens.push({ text: char, visible: false });
      continue;
    }
    line += char;
  }
  flushLine();
  return tokens;
}

function tokensToText(tokens: DirectionalToken[]) {
  return tokens.map((token) => token.text).join("");
}

function visibleDirectionalUnitLength(value: string) {
  return directionalTextTokens(value, false).filter((token) => token.visible).length;
}

function sliceVisibleDirectionalText(
  value: string,
  visibleCharacters: number,
  options: { preserveLeadingWhitespace?: boolean; preserveWhitespaceOnly?: boolean } = {},
) {
  const tokens = directionalTextTokens(value, false);
  let remaining = Math.max(0, visibleCharacters);
  let output = "";
  let emittedVisible = options.preserveLeadingWhitespace === true;
  for (const token of tokens) {
    if (token.visible) {
      if (remaining <= 0) {
        break;
      }
      output += token.text;
      emittedVisible = true;
      remaining -= 1;
      continue;
    }
    if (emittedVisible && remaining > 0) {
      output += token.text;
    }
  }
  if (options.preserveWhitespaceOnly && output.trim() === "") {
    return output;
  }
  return output.replace(/[^\S\r\n]+$/u, "");
}

function reorderRtlPlainText(value: string, options: { preserveWhitespaceOnly?: boolean } = {}) {
  const reordered = tokensToText(directionalTextTokens(value, true));
  if (options.preserveWhitespaceOnly && value.trim() === "") {
    return reordered;
  }
  return reordered.replace(/[^\S\r\n]+$/u, "");
}

function visibleTextLength(value: string) {
  return codepoints(value).filter((char) => !isLineBreakCharacter(char)).length;
}

function sliceVisibleTextLtr(value: string, visibleCharacters: number) {
  const chars = codepoints(value);
  let remaining = Math.max(0, visibleCharacters);
  let output = "";
  let emittedVisible = 0;
  for (const char of chars) {
    if (isLineBreakCharacter(char)) {
      if (emittedVisible > 0 && remaining > 0) {
        output += char;
      }
      continue;
    }
    if (remaining <= 0) {
      break;
    }
    output += char;
    remaining -= 1;
    emittedVisible += 1;
  }
  return output;
}

function sliceVisibleText(value: string, visibleCharacters: number, direction: DialogTypewriterDirection) {
  return direction === "rtl"
    ? sliceVisibleDirectionalText(reorderRtlPlainText(value), visibleCharacters)
    : sliceVisibleTextLtr(value, visibleCharacters);
}

const parsedTemplateCache = new Map<string, DocumentFragment>();

function createTemplate(html: string) {
  if (typeof document === "undefined") {
    return null;
  }
  const template = document.createElement("template");
  const cached = parsedTemplateCache.get(html);
  if (cached) {
    parsedTemplateCache.delete(html);
    parsedTemplateCache.set(html, cached);
    template.content.append(cached.cloneNode(true));
    return template;
  }
  const fragment = parseHtmlFragment(html);
  if (!fragment) {
    return null;
  }
  template.content.append(fragment);
  refreshCacheEntry(parsedTemplateCache, html, template.content.cloneNode(true) as DocumentFragment);
  return template;
}

function htmlPlainText(html: string) {
  const template = createTemplate(html);
  return template ? (template.content.textContent ?? "") : stripHtmlFallback(html);
}

const allowedDialogTagNames = ["a", "b", "br", "code", "em", "i", "p", "s", "span", "strong"] as const;
export type DialogHtmlTag = (typeof allowedDialogTagNames)[number];
export type DialogHtmlStyleProperty =
  | "color"
  | "font-style"
  | "font-weight"
  | "letter-spacing"
  | "line-height"
  | "text-decoration";

export type DialogHtmlNode =
  | { kind: "text"; text: string }
  | {
      attrs?: {
        className?: string;
        href?: string;
        rel?: string;
        style?: Partial<Record<DialogHtmlStyleProperty, string>>;
        target?: string;
      };
      children: DialogHtmlNode[];
      kind: "element";
      tag: DialogHtmlTag;
    };

const allowedDialogTags = new Set<string>(allowedDialogTagNames);
const removedDialogTags = new Set(["embed", "iframe", "link", "meta", "object", "script", "style"]);
const allowedDialogClasses = new Set(["dialog-layer__md-bullet", "dialog-layer__md-quote"]);
const allowedDialogStylePropertyNames = [
  "color",
  "font-style",
  "font-weight",
  "letter-spacing",
  "line-height",
  "text-decoration",
] as const;
const allowedDialogStyleProperties = new Set<string>(allowedDialogStylePropertyNames);

function isSafeCssValue(property: string, value: string) {
  const next = value.trim();
  if (!next || /(?:expression|javascript:|url\s*\(|@import|[<>])/i.test(next)) {
    return false;
  }
  if (property === "color") {
    return (
      /^#[\da-f]{3,8}$/i.test(next) ||
      /^[a-z][a-z0-9_-]{0,31}$/i.test(next) ||
      /^rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\)$/i.test(next)
    );
  }
  if (property === "font-weight") {
    return /^(?:normal|bold|[1-9]00)$/i.test(next);
  }
  if (property === "font-style") {
    return /^(?:normal|italic|oblique)$/i.test(next);
  }
  if (property === "line-height") {
    return /^(?:normal|[\d.]+(?:px|em|rem|%)?)$/i.test(next);
  }
  if (property === "letter-spacing") {
    return /^(?:normal|-?[\d.]+(?:px|em|rem))$/i.test(next);
  }
  if (property === "text-decoration") {
    return /^(?:none|underline|line-through|overline)$/i.test(next);
  }
  return false;
}

function sanitizeDialogStyle(value: string) {
  return value
    .split(";")
    .map((declaration) => {
      const [rawProperty, ...rawValueParts] = declaration.split(":");
      const property = rawProperty?.trim().toLowerCase() ?? "";
      const nextValue = rawValueParts.join(":").trim();
      if (!allowedDialogStyleProperties.has(property) || !isSafeCssValue(property, nextValue)) {
        return "";
      }
      return `${property}: ${nextValue}`;
    })
    .filter(Boolean)
    .join("; ");
}

function dialogStyleRecord(value: string) {
  const style: Partial<Record<DialogHtmlStyleProperty, string>> = {};
  value.split(";").forEach((declaration) => {
    const [rawProperty, ...rawValueParts] = declaration.split(":");
    const property = rawProperty?.trim().toLowerCase() ?? "";
    const nextValue = rawValueParts.join(":").trim();
    if (!allowedDialogStyleProperties.has(property) || !isSafeCssValue(property, nextValue)) {
      return;
    }
    style[property as DialogHtmlStyleProperty] = nextValue;
  });
  return style;
}

function sanitizeDialogLink(value: string) {
  const trimmed = value.trim();
  if (/^(?:https?:|mailto:)/i.test(trimmed)) {
    return trimmed;
  }
  return "";
}

function sanitizeDialogElement(element: Element) {
  const tag = element.tagName.toLowerCase();
  if (removedDialogTags.has(tag)) {
    element.remove();
    return;
  }
  if (!allowedDialogTags.has(tag)) {
    element.replaceWith(document.createTextNode(element.textContent ?? ""));
    return;
  }

  for (const attribute of Array.from(element.attributes)) {
    const name = attribute.name.toLowerCase();
    const value = attribute.value;
    if (name === "style") {
      const style = sanitizeDialogStyle(value);
      if (style) {
        element.setAttribute("style", style);
      } else {
        element.removeAttribute(attribute.name);
      }
      continue;
    }
    if (name === "class") {
      const classes = value
        .split(/\s+/)
        .map((item) => item.trim())
        .filter((item) => allowedDialogClasses.has(item));
      if (classes.length) {
        element.setAttribute("class", classes.join(" "));
      } else {
        element.removeAttribute(attribute.name);
      }
      continue;
    }
    if (tag === "a" && name === "href") {
      const href = sanitizeDialogLink(value);
      if (href) {
        element.setAttribute("href", href);
        element.setAttribute("rel", "noreferrer");
        element.setAttribute("target", "_blank");
      } else {
        element.removeAttribute(attribute.name);
      }
      continue;
    }
    if (name === "data-created-at" && /^\d{10,}$/.test(value.trim())) {
      continue;
    }
    element.removeAttribute(attribute.name);
  }
}

function sanitizeDialogNode(node: Node) {
  if (node.nodeType === Node.ELEMENT_NODE) {
    const element = node as Element;
    sanitizeDialogElement(element);
    if (!element.isConnected && element.parentNode == null) {
      return;
    }
    Array.from(element.childNodes).forEach(sanitizeDialogNode);
    return;
  }
  if (node.nodeType !== Node.TEXT_NODE) {
    node.parentNode?.removeChild(node);
  }
}

function dialogElementAttrs(element: Element) {
  const attrs: Extract<DialogHtmlNode, { kind: "element" }>["attrs"] = {};
  const className = element.getAttribute("class") ?? "";
  const classes = className
    .split(/\s+/)
    .map((item) => item.trim())
    .filter((item) => allowedDialogClasses.has(item));
  if (classes.length) {
    attrs.className = classes.join(" ");
  }

  const style = dialogStyleRecord(element.getAttribute("style") ?? "");
  if (Object.keys(style).length) {
    attrs.style = style;
  }

  if (element.tagName.toLowerCase() === "a") {
    const href = sanitizeDialogLink(element.getAttribute("href") ?? "");
    if (href) {
      attrs.href = href;
      attrs.rel = "noreferrer";
      attrs.target = "_blank";
    }
  }

  return Object.keys(attrs).length ? attrs : undefined;
}

function dialogNodeFromDom(node: Node): DialogHtmlNode | null {
  if (node.nodeType === Node.TEXT_NODE) {
    return { kind: "text", text: node.textContent ?? "" };
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }
  const element = node as Element;
  const tag = element.tagName.toLowerCase();
  if (!allowedDialogTags.has(tag)) {
    const text = element.textContent ?? "";
    return text ? { kind: "text", text } : null;
  }
  return {
    attrs: dialogElementAttrs(element),
    children: dialogNodesFromParent(element),
    kind: "element",
    tag: tag as DialogHtmlTag,
  };
}

function dialogNodesFromParent(parent: ParentNode): DialogHtmlNode[] {
  return Array.from(parent.childNodes).flatMap((node) => {
    const next = dialogNodeFromDom(node);
    return next ? [next] : [];
  });
}

export function sanitizeDialogHtml(html: string) {
  const template = createTemplate(html);
  if (!template) {
    return stripHtmlFallback(html);
  }
  Array.from(template.content.childNodes).forEach(sanitizeDialogNode);
  const wrapper = document.createElement("div");
  wrapper.append(template.content.cloneNode(true));
  return wrapper.innerHTML;
}

function countNodeText(node: Node): number {
  if (node.nodeType === Node.TEXT_NODE) {
    return codepoints(node.textContent ?? "").length;
  }
  let total = 0;
  node.childNodes.forEach((child) => {
    total += countNodeText(child);
  });
  return total;
}

function countNodeTextUnits(node: Node): number {
  if (node.nodeType === Node.TEXT_NODE) {
    return visibleDirectionalUnitLength(node.textContent ?? "");
  }
  let total = 0;
  node.childNodes.forEach((child) => {
    total += countNodeTextUnits(child);
  });
  return total;
}

function cloneNodeUntil(node: Node, remaining: { value: number }): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.textContent ?? "";
    if (!text) {
      return document.createTextNode("");
    }
    const next = sliceCodepoints(text, remaining.value);
    remaining.value = Math.max(0, remaining.value - codepoints(next).length);
    return next ? document.createTextNode(next) : null;
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as Element;
  if (remaining.value <= 0 && element.tagName.toLowerCase() === "br") {
    return null;
  }
  const clone = element.cloneNode(false) as Element;
  for (const child of Array.from(element.childNodes)) {
    const nextChild = cloneNodeUntil(child, remaining);
    if (nextChild) {
      clone.appendChild(nextChild);
    }
    if (remaining.value <= 0) {
      break;
    }
  }
  return clone;
}

function cloneNodeUntilUnits(node: Node, remaining: { emitted?: boolean; value: number }): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.textContent ?? "";
    if (!text) {
      return document.createTextNode("");
    }
    const next = sliceVisibleDirectionalText(text, remaining.value, {
      preserveLeadingWhitespace: remaining.emitted === true,
      preserveWhitespaceOnly: remaining.emitted === true,
    });
    const visibleUnits = visibleDirectionalUnitLength(next);
    remaining.value = Math.max(0, remaining.value - visibleUnits);
    if (visibleUnits > 0) {
      remaining.emitted = true;
    }
    return next ? document.createTextNode(next) : null;
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as Element;
  if (remaining.value <= 0 && element.tagName.toLowerCase() === "br") {
    return null;
  }
  const clone = element.cloneNode(false) as Element;
  if (element.tagName.toLowerCase() === "br") {
    remaining.emitted = false;
    return clone;
  }
  for (const child of Array.from(element.childNodes)) {
    const nextChild = cloneNodeUntilUnits(child, remaining);
    if (nextChild) {
      clone.appendChild(nextChild);
    }
    if (remaining.value <= 0) {
      break;
    }
  }
  return clone;
}

export type DialogTypewriterDirection = "ltr" | "rtl";

function normalizeTypewriterDirection(direction?: string): DialogTypewriterDirection {
  return direction === "rtl" ? "rtl" : "ltr";
}

function stripLeadingSpeakerSeparator(text: string) {
  const chars = codepoints(text);
  let index = 0;
  while (index < chars.length && /\s/u.test(chars[index] ?? "")) {
    index += 1;
  }
  if ((chars[index] ?? "") === "：" || (chars[index] ?? "") === ":") {
    index += 1;
  }
  while (index < chars.length && /\s/u.test(chars[index] ?? "")) {
    index += 1;
  }
  return chars.slice(index).join("");
}

function leadingSpeakerTextPattern(characterName: string) {
  return new RegExp(`^\\s*${escapeRegExp(characterName.trim())}\\s*[：:]\\s*`, "u");
}

function leadingSpeakerHtmlLabelMatch(label: string, characterName: string) {
  const escapedName = escapeRegExp(characterName.trim());
  const nameOnlyPattern = new RegExp(`^\\s*${escapedName}\\s*$`, "u");
  const labelWithSeparatorPattern = new RegExp(`^\\s*${escapedName}\\s*[：:]\\s*$`, "u");
  if (labelWithSeparatorPattern.test(label)) {
    return { hasSeparator: true, matches: true };
  }
  if (nameOnlyPattern.test(label)) {
    return { hasSeparator: false, matches: true };
  }
  return { hasSeparator: false, matches: false };
}

function firstMeaningfulSiblingAfter(node: Node) {
  let next = node.nextSibling;
  while (next) {
    if (next.nodeType === Node.TEXT_NODE && !(next.textContent ?? "").trim()) {
      next = next.nextSibling;
      continue;
    }
    return next;
  }
  return null;
}

function startsWithSpeakerSeparator(node: Node | null) {
  return node?.nodeType === Node.TEXT_NODE && /^\s*[：:]/u.test(node.textContent ?? "");
}

function firstMeaningfulChild(parent: ParentNode) {
  for (const child of Array.from(parent.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE && !(child.textContent ?? "").trim()) {
      continue;
    }
    return child;
  }
  return null;
}

function stripLeadingSpeakerFromParent(parent: ParentNode, characterName: string) {
  const first = firstMeaningfulChild(parent);
  if (!first) {
    return false;
  }
  if (first.nodeType === Node.ELEMENT_NODE && (first as Element).tagName.toLowerCase() !== "b") {
    return stripLeadingSpeakerFromParent(first as Element, characterName);
  }
  if (first.nodeType !== Node.ELEMENT_NODE || (first as Element).tagName.toLowerCase() !== "b") {
    return false;
  }
  const speakerMatch = leadingSpeakerHtmlLabelMatch(first.textContent ?? "", characterName);
  if (!speakerMatch.matches) {
    return false;
  }
  const owner = first.parentNode;
  if (!owner) {
    return false;
  }
  if (!speakerMatch.hasSeparator && !startsWithSpeakerSeparator(firstMeaningfulSiblingAfter(first))) {
    return false;
  }
  owner.removeChild(first);
  const next = firstMeaningfulChild(owner);
  if (next?.nodeType === Node.TEXT_NODE) {
    next.textContent = stripLeadingSpeakerSeparator(next.textContent ?? "");
    if (!next.textContent) {
      next.parentNode?.removeChild(next);
    }
  }
  return true;
}

export function stripLeadingSpeakerHtml(html: string, characterName?: string) {
  if (!characterName?.trim() || !html.trim()) {
    return html;
  }
  const template = createTemplate(html);
  if (!template) {
    return html;
  }
  if (!stripLeadingSpeakerFromParent(template.content, characterName)) {
    return html;
  }
  const wrapper = document.createElement("div");
  wrapper.append(template.content.cloneNode(true));
  return wrapper.innerHTML;
}

export function stripLeadingSpeakerText(text: string, characterName?: string) {
  if (!characterName?.trim()) {
    return text;
  }
  return text.replace(leadingSpeakerTextPattern(characterName), "");
}

export function countVisibleHtmlCharacters(html: string) {
  const template = createTemplate(html);
  if (!template) {
    return codepoints(stripHtmlFallback(html)).length;
  }
  let total = 0;
  template.content.childNodes.forEach((node) => {
    total += countNodeText(node);
  });
  return total;
}

export function countVisibleHtmlUnits(html: string) {
  const template = createTemplate(html);
  if (!template) {
    return visibleDirectionalUnitLength(stripHtmlFallback(html));
  }
  let total = 0;
  template.content.childNodes.forEach((node) => {
    total += countNodeTextUnits(node);
  });
  return total;
}

function cloneNodeAsRtlVisual(node: Node): Node | null {
  if (node.nodeType === Node.TEXT_NODE) {
    return document.createTextNode(reorderRtlPlainText(node.textContent ?? "", { preserveWhitespaceOnly: true }));
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }
  const clone = node.cloneNode(false) as Element;
  let lineNodes: Node[] = [];
  const appendLine = () => {
    for (const child of [...lineNodes].reverse()) {
      const nextChild = cloneNodeAsRtlVisual(child);
      if (nextChild) {
        clone.appendChild(nextChild);
      }
    }
    lineNodes = [];
  };
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === Node.ELEMENT_NODE && (child as Element).tagName.toLowerCase() === "br") {
      appendLine();
      const nextChild = cloneNodeAsRtlVisual(child);
      if (nextChild) {
        clone.appendChild(nextChild);
      }
      continue;
    }
    lineNodes.push(child);
  }
  appendLine();
  return clone;
}

export function reorderHtmlForRtl(html: string) {
  const template = createTemplate(html);
  if (!template) {
    return reorderRtlPlainText(stripHtmlFallback(html));
  }
  const wrapper = document.createElement("div");
  for (const node of Array.from(template.content.childNodes)) {
    const nextNode = cloneNodeAsRtlVisual(node);
    if (nextNode) {
      wrapper.appendChild(nextNode);
    }
  }
  return wrapper.innerHTML;
}

export function renderDialogHtmlFrame(
  html: string,
  visibleCharacters: number,
  direction: DialogTypewriterDirection = "ltr",
) {
  return renderDialogHtmlFrameContent(html, visibleCharacters, direction).html;
}

function renderDialogHtmlFrameContent(
  html: string,
  visibleCharacters: number,
  direction: DialogTypewriterDirection = "ltr",
) {
  const normalizedDirection = normalizeTypewriterDirection(direction);
  const template = createTemplate(html);
  if (!template) {
    const text = sliceVisibleText(htmlPlainText(html), visibleCharacters, normalizedDirection);
    return { html: text, nodes: text ? [{ kind: "text" as const, text }] : [] };
  }
  const wrapper = document.createElement("div");
  const remaining = { value: Math.max(0, visibleCharacters) };
  if (normalizedDirection === "rtl") {
    for (const node of Array.from(template.content.childNodes)) {
      const nextNode = cloneNodeUntilUnits(node, remaining);
      if (nextNode) {
        wrapper.appendChild(nextNode);
      }
      if (remaining.value <= 0) {
        break;
      }
    }
    return { html: wrapper.innerHTML, nodes: dialogNodesFromParent(wrapper) };
  }
  for (const node of Array.from(template.content.childNodes)) {
    const nextNode = cloneNodeUntil(node, remaining);
    if (nextNode) {
      wrapper.appendChild(nextNode);
    }
    if (remaining.value <= 0) {
      break;
    }
  }
  return { html: wrapper.innerHTML, nodes: dialogNodesFromParent(wrapper) };
}

export interface DialogTypewriterSource {
  cacheKey: string;
  fullHtml?: string;
  fullRtlHtml?: string;
  fullRtlText: string;
  fullText: string;
  totalRtlCharacters: number;
  totalCharacters: number;
}

const dialogTypewriterSourceCache = new Map<string, DialogTypewriterSource>();

function sourceInputCacheKey(input: { characterName?: string; html?: string; text?: string }) {
  return JSON.stringify([input.characterName ?? "", input.html ?? "", input.text ?? ""]);
}

export function buildDialogTypewriterSource(input: {
  characterName?: string;
  html?: string;
  text?: string;
}): DialogTypewriterSource {
  const inputCacheKey = sourceInputCacheKey(input);
  const cached = dialogTypewriterSourceCache.get(inputCacheKey);
  if (cached) {
    dialogTypewriterSourceCache.delete(inputCacheKey);
    dialogTypewriterSourceCache.set(inputCacheKey, cached);
    return cached;
  }
  const normalizedHtml = input.html?.trim()
    ? sanitizeDialogHtml(stripLeadingSpeakerHtml(input.html, input.characterName))
    : undefined;
  const normalizedText = stripLeadingSpeakerText(input.text ?? "", input.characterName);
  const normalizedMarkdownHtml = normalizedText.trim() ? markdownToDialogHtml(normalizedText) : undefined;
  const buildSource = (cacheKey: string, fullText: string, fullHtml?: string): DialogTypewriterSource => {
    const fullRtlHtml = fullHtml ? reorderHtmlForRtl(fullHtml) : undefined;
    const fullRtlText = reorderRtlPlainText(fullText);
    return {
      cacheKey,
      fullHtml,
      fullRtlHtml,
      fullRtlText,
      fullText,
      totalCharacters: fullHtml ? countVisibleHtmlCharacters(fullHtml) : visibleTextLength(fullText),
      totalRtlCharacters: fullRtlHtml ? countVisibleHtmlUnits(fullRtlHtml) : visibleDirectionalUnitLength(fullRtlText),
    };
  };
  const source = normalizedHtml
    ? buildSource(`html:${normalizedHtml}`, normalizedText, normalizedHtml)
    : normalizedMarkdownHtml
      ? buildSource(`markdown:${normalizedText}`, normalizedText, normalizedMarkdownHtml)
      : buildSource(`text:${normalizedText}`, normalizedText);
  refreshCacheEntry(dialogTypewriterSourceCache, inputCacheKey, source);
  return source;
}

export function renderDialogTypewriterFrame(
  source: DialogTypewriterSource,
  visibleCharacters: number,
  direction: DialogTypewriterDirection = "ltr",
) {
  const frame = renderDialogTypewriterRichFrame(source, visibleCharacters, direction);
  return {
    html: frame.html,
    text: frame.text,
  };
}

export function renderDialogTypewriterRichFrame(
  source: DialogTypewriterSource,
  visibleCharacters: number,
  direction: DialogTypewriterDirection = "ltr",
) {
  const normalizedDirection = normalizeTypewriterDirection(direction);
  if (source.fullHtml) {
    const html = normalizedDirection === "rtl" ? (source.fullRtlHtml ?? source.fullHtml) : source.fullHtml;
    const frame = renderDialogHtmlFrameContent(html, visibleCharacters, normalizedDirection);
    return {
      html: frame.html,
      nodes: frame.nodes,
      text:
        normalizedDirection === "rtl"
          ? sliceVisibleDirectionalText(source.fullRtlText, visibleCharacters)
          : sliceVisibleText(source.fullText, visibleCharacters, normalizedDirection),
    };
  }
  const text =
    normalizedDirection === "rtl"
      ? sliceVisibleDirectionalText(source.fullRtlText, visibleCharacters)
      : sliceVisibleText(source.fullText, visibleCharacters, normalizedDirection);
  return {
    html: text,
    nodes: text ? [{ kind: "text" as const, text }] : [],
    text,
  };
}
