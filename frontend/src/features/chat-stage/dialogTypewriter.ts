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

function visibleTextLength(value: string) {
  return codepoints(value).filter((char) => !isLineBreakCharacter(char)).length;
}

function sliceVisibleText(value: string, visibleCharacters: number) {
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

function createTemplate(html: string) {
  if (typeof document === "undefined") {
    return null;
  }
  const template = document.createElement("template");
  template.innerHTML = html;
  return template;
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

export function stripLeadingSpeakerHtml(html: string, characterName?: string) {
  if (!characterName?.trim() || !html.trim()) {
    return html;
  }
  return html.replace(/<b[^>]*>[^<]+<\/b>[：:]?\s*/, "");
}

export function stripLeadingSpeakerText(text: string, characterName?: string) {
  if (!characterName?.trim()) {
    return text;
  }
  const pattern = new RegExp(`^\\s*${escapeRegExp(characterName.trim())}\\s*[：:]\\s*`);
  return text.replace(pattern, "");
}

export function countVisibleHtmlCharacters(html: string) {
  const template = createTemplate(html);
  if (!template) {
    return codepoints(html.replace(/<[^>]+>/g, "")).length;
  }
  let total = 0;
  template.content.childNodes.forEach((node) => {
    total += countNodeText(node);
  });
  return total;
}

export function renderDialogHtmlFrame(html: string, visibleCharacters: number) {
  const template = createTemplate(html);
  if (!template) {
    return sliceCodepoints(html.replace(/<[^>]+>/g, ""), visibleCharacters);
  }
  const wrapper = document.createElement("div");
  const remaining = { value: Math.max(0, visibleCharacters) };
  for (const node of Array.from(template.content.childNodes)) {
    const nextNode = cloneNodeUntil(node, remaining);
    if (nextNode) {
      wrapper.appendChild(nextNode);
    }
    if (remaining.value <= 0) {
      break;
    }
  }
  return wrapper.innerHTML;
}

export interface DialogTypewriterSource {
  cacheKey: string;
  fullHtml?: string;
  fullText: string;
  totalCharacters: number;
}

export function buildDialogTypewriterSource(input: {
  characterName?: string;
  html?: string;
  text?: string;
}): DialogTypewriterSource {
  const normalizedHtml = input.html?.trim() ? stripLeadingSpeakerHtml(input.html, input.characterName) : undefined;
  const normalizedText = stripLeadingSpeakerText(input.text ?? "", input.characterName);
  if (normalizedHtml) {
    return {
      cacheKey: `html:${normalizedHtml}`,
      fullHtml: normalizedHtml,
      fullText: normalizedText,
      totalCharacters: countVisibleHtmlCharacters(normalizedHtml),
    };
  }
  return {
    cacheKey: `text:${normalizedText}`,
    fullText: normalizedText,
    totalCharacters: visibleTextLength(normalizedText),
  };
}

export function renderDialogTypewriterFrame(source: DialogTypewriterSource, visibleCharacters: number) {
  if (source.fullHtml) {
    return {
      html: renderDialogHtmlFrame(source.fullHtml, visibleCharacters),
      text: sliceVisibleText(source.fullText, visibleCharacters),
    };
  }
  return {
    html: undefined,
    text: sliceVisibleText(source.fullText, visibleCharacters),
  };
}
