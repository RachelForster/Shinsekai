function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeUrl(value: string) {
  const trimmed = value.trim();
  if (/^(?:https?:|mailto:)/i.test(trimmed)) {
    return trimmed;
  }
  return "";
}

function renderInlineMarkdown(value: string) {
  const codeSpans: string[] = [];
  const linkSpans: string[] = [];
  let protectedText = value.replace(/`([^`]+)`/g, (_match, code: string) => {
    const index = codeSpans.push(`<code>${escapeHtml(code)}</code>`) - 1;
    return `\u0000CODE${index}\u0000`;
  });

  protectedText = protectedText.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, label: string, url: string) => {
    const href = normalizeUrl(url);
    const html = href
      ? `<a href="${escapeHtml(href)}" rel="noreferrer" target="_blank">${renderInlineMarkdown(label)}</a>`
      : escapeHtml(label);
    const index = linkSpans.push(html) - 1;
    return `\u0000LINK${index}\u0000`;
  });

  let escaped = escapeHtml(protectedText);
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  escaped = escaped.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  escaped = escaped.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  escaped = escaped.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  escaped = escaped.replace(/~~([^~]+)~~/g, "<s>$1</s>");

  return escaped
    .replace(/\u0000LINK(\d+)\u0000/g, (_match, index: string) => linkSpans[Number(index)] ?? "")
    .replace(/\u0000CODE(\d+)\u0000/g, (_match, index: string) => codeSpans[Number(index)] ?? "");
}

function renderMarkdownLine(line: string) {
  const heading = line.match(/^\s{0,3}(#{1,3})\s+(.+)$/);
  if (heading) {
    return `<strong>${renderInlineMarkdown(heading[2] ?? "")}</strong>`;
  }

  const unordered = line.match(/^\s{0,3}[-*+]\s+(.+)$/);
  if (unordered) {
    return `<span class="dialog-layer__md-bullet">•</span> ${renderInlineMarkdown(unordered[1] ?? "")}`;
  }

  const ordered = line.match(/^\s{0,3}\d+[.)]\s+(.+)$/);
  if (ordered) {
    return `<span class="dialog-layer__md-bullet">•</span> ${renderInlineMarkdown(ordered[1] ?? "")}`;
  }

  const quote = line.match(/^\s{0,3}>\s?(.+)$/);
  if (quote) {
    return `<span class="dialog-layer__md-quote">${renderInlineMarkdown(quote[1] ?? "")}</span>`;
  }

  return renderInlineMarkdown(line);
}

export function markdownToDialogHtml(text: string) {
  return text
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd())
    .map((line) => (line ? renderMarkdownLine(line) : ""))
    .join("<br>");
}
