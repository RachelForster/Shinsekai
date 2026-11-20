/**
 * Zero-dependency YAML subset parser & serializer tailored for Shinsekai `character.yaml`.
 * Handles PyYAML output (top-level list, nested dicts/lists, block literal/folded multiline
 * strings, single/double quoted strings with escapes, booleans, numbers, nulls, and JSON flow).
 */

interface YamlLine {
  indent: number;
  text: string;
  raw: string;
}

function stripInlineComment(line: string): string {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === "'" && !inDouble) {
      if (inSingle && line[i + 1] === "'") {
        i += 1;
        continue;
      }
      inSingle = !inSingle;
    } else if (ch === '"' && !inSingle) {
      if (ch === '"' && line[i - 1] !== "\\") {
        inDouble = !inDouble;
      }
    } else if (ch === "#" && !inSingle && !inDouble) {
      if (i === 0 || /\s/.test(line[i - 1])) {
        return line.slice(0, i).trimEnd();
      }
    }
  }
  return line;
}

function unquoteDouble(raw: string): string {
  const inner = raw.slice(1, -1);
  let out = "";
  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (ch !== "\\" || i + 1 >= inner.length) {
      out += ch;
      continue;
    }
    const next = inner[i + 1];
    i += 1;
    switch (next) {
      case "n":
        out += "\n";
        break;
      case "r":
        out += "\r";
        break;
      case "t":
        out += "\t";
        break;
      case "\\":
        out += "\\";
        break;
      case '"':
        out += '"';
        break;
      case "'":
        out += "'";
        break;
      case "0":
        out += "\0";
        break;
      case "x": {
        const hex = inner.slice(i + 1, i + 3);
        if (/^[0-9a-fA-F]{2}$/.test(hex)) {
          out += String.fromCharCode(parseInt(hex, 16));
          i += 2;
        }
        break;
      }
      case "u": {
        const hex = inner.slice(i + 1, i + 5);
        if (/^[0-9a-fA-F]{4}$/.test(hex)) {
          out += String.fromCharCode(parseInt(hex, 16));
          i += 4;
        }
        break;
      }
      default:
        out += next;
        break;
    }
  }
  return out;
}

function splitTopLevelCommas(inner: string): string[] {
  const parts: string[] = [];
  let current = "";
  let depthBracket = 0;
  let depthBrace = 0;
  let inSingle = false;
  let inDouble = false;

  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (ch === "'" && !inDouble) {
      inSingle = !inSingle;
      current += ch;
    } else if (ch === '"' && !inSingle && inner[i - 1] !== "\\") {
      inDouble = !inDouble;
      current += ch;
    } else if (!inSingle && !inDouble) {
      if (ch === "[") depthBracket += 1;
      else if (ch === "]") depthBracket -= 1;
      else if (ch === "{") depthBrace += 1;
      else if (ch === "}") depthBrace -= 1;
      else if (ch === "," && depthBracket === 0 && depthBrace === 0) {
        parts.push(current.trim());
        current = "";
        continue;
      }
      current += ch;
    } else {
      current += ch;
    }
  }
  if (current.trim()) {
    parts.push(current.trim());
  }
  return parts;
}

function findUnquotedColon(text: string): number {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "'" && !inDouble) {
      if (inSingle && text[i + 1] === "'") {
        i += 1;
        continue;
      }
      inSingle = !inSingle;
    } else if (ch === '"' && !inSingle && text[i - 1] !== "\\") {
      inDouble = !inDouble;
    } else if (ch === ":" && !inSingle && !inDouble) {
      if (i + 1 === text.length || /\s/.test(text[i + 1])) {
        return i;
      }
    }
  }
  return -1;
}

function parseScalar(raw: string): unknown {
  const value = raw.trim();
  if (!value || value === "null" || value === "Null" || value === "NULL" || value === "~") {
    return null;
  }
  if (value === "true" || value === "True" || value === "TRUE") return true;
  if (value === "false" || value === "False" || value === "FALSE") return false;
  if (value === "[]") return [];
  if (value === "{}") return {};

  if (value.startsWith("'") && value.endsWith("'") && value.length >= 2) {
    return value.slice(1, -1).replace(/''/g, "'");
  }
  if (value.startsWith('"') && value.endsWith('"') && value.length >= 2) {
    return unquoteDouble(value);
  }
  if (/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value)) {
    const num = Number(value);
    if (Number.isFinite(num)) return num;
  }
  if (value.startsWith("[") && value.endsWith("]")) {
    const inner = value.slice(1, -1).trim();
    if (!inner) return [];
    return splitTopLevelCommas(inner).map((item) => parseScalar(item));
  }
  if (value.startsWith("{") && value.endsWith("}")) {
    const inner = value.slice(1, -1).trim();
    if (!inner) return {};
    const obj: Record<string, unknown> = {};
    for (const pair of splitTopLevelCommas(inner)) {
      const colonIdx = findUnquotedColon(pair);
      if (colonIdx > 0) {
        const key = String(parseScalar(pair.slice(0, colonIdx)));
        obj[key] = parseScalar(pair.slice(colonIdx + 1));
      }
    }
    return obj;
  }
  return value;
}

function tokenizeYamlLines(source: string): YamlLine[] {
  const rawLines = source.replace(/^\uFEFF/, "").split(/\r?\n/);
  const result: YamlLine[] = [];
  for (const raw of rawLines) {
    const cleaned = stripInlineComment(raw);
    if (!cleaned.trim() || cleaned.trim() === "---" || cleaned.trim() === "...") {
      result.push({ indent: -1, text: "", raw });
      continue;
    }
    const indent = cleaned.search(/\S|$/);
    result.push({
      indent,
      text: cleaned.slice(indent),
      raw,
    });
  }
  return result;
}

function parseBlockScalar(
  lines: YamlLine[],
  startIndex: number,
  parentIndent: number,
  style: string,
): { value: string; nextIndex: number } {
  const isFolded = style.startsWith(">");
  const chomp = style.endsWith("-") ? "strip" : style.endsWith("+") ? "keep" : "clip";
  const collected: string[] = [];
  let blockIndent: number | null = null;
  let i = startIndex;

  while (i < lines.length) {
    const rawLine = lines[i].raw;
    if (!rawLine.trim()) {
      collected.push("");
      i += 1;
      continue;
    }
    const indent = rawLine.search(/\S|$/);
    if (blockIndent === null) {
      if (indent <= parentIndent) break;
      blockIndent = indent;
    } else if (indent < blockIndent) {
      break;
    }
    collected.push(rawLine.slice(blockIndent));
    i += 1;
  }

  let end = collected.length;
  if (chomp !== "keep") {
    while (end > 0 && collected[end - 1] === "") {
      end -= 1;
    }
  }
  const sliced = collected.slice(0, end);
  let text = isFolded
    ? sliced
        .map((line) => (line === "" ? "\n" : line))
        .join(" ")
        .replace(/ \n /g, "\n")
    : sliced.join("\n");

  if (chomp === "clip" && sliced.length > 0) {
    text += "\n";
  }
  return { value: text, nextIndex: i };
}

function skipBlanks(lines: YamlLine[], index: number): number {
  let i = index;
  while (i < lines.length && lines[i].indent < 0) {
    i += 1;
  }
  return i;
}

function parseNode(lines: YamlLine[], startIndex: number, minIndent: number): { value: unknown; nextIndex: number } {
  const idx = skipBlanks(lines, startIndex);
  if (idx >= lines.length || lines[idx].indent < minIndent) {
    return { value: null, nextIndex: idx };
  }
  const line = lines[idx];
  if (line.text === "-" || line.text.startsWith("- ")) {
    return parseSequence(lines, idx, line.indent);
  }
  if (findUnquotedColon(line.text) >= 0) {
    return parseMapping(lines, idx, line.indent);
  }
  return { value: parseScalar(line.text), nextIndex: idx + 1 };
}

function parseSequence(
  lines: YamlLine[],
  startIndex: number,
  seqIndent: number,
): { value: unknown[]; nextIndex: number } {
  const items: unknown[] = [];
  let i = startIndex;

  while (i < lines.length) {
    i = skipBlanks(lines, i);
    if (i >= lines.length) break;
    const line = lines[i];
    if (line.indent !== seqIndent) break;
    if (!(line.text === "-" || line.text.startsWith("- "))) break;

    const afterDash = line.text.slice(1).trim();
    if (!afterDash) {
      const nested = parseNode(lines, i + 1, seqIndent + 1);
      items.push(nested.value);
      i = nested.nextIndex;
      continue;
    }

    if (/^[|>][+-]?$/.test(afterDash)) {
      const block = parseBlockScalar(lines, i + 1, seqIndent, afterDash);
      items.push(block.value);
      i = block.nextIndex;
      continue;
    }

    const colonPos = findUnquotedColon(afterDash);
    if (colonPos >= 0) {
      // Sequence item begins an inline mapping on the "- key: val" line
      const itemIndent = seqIndent + 2;
      const synthetic: YamlLine[] = [
        ...lines.slice(0, i),
        { indent: itemIndent, text: afterDash, raw: `${" ".repeat(itemIndent)}${afterDash}` },
        ...lines.slice(i + 1),
      ];
      const mapResult = parseMapping(synthetic, i, itemIndent);
      items.push(mapResult.value);
      i = mapResult.nextIndex;
      continue;
    }

    items.push(parseScalar(afterDash));
    i += 1;
  }

  return { value: items, nextIndex: i };
}

function parseMapping(
  lines: YamlLine[],
  startIndex: number,
  mapIndent: number,
): { value: Record<string, unknown>; nextIndex: number } {
  const obj: Record<string, unknown> = {};
  let i = startIndex;

  while (i < lines.length) {
    i = skipBlanks(lines, i);
    if (i >= lines.length) break;
    const line = lines[i];
    if (line.indent !== mapIndent) break;
    if (line.text === "-" || line.text.startsWith("- ")) break;

    const colonPos = findUnquotedColon(line.text);
    if (colonPos < 0) break;

    const key = String(parseScalar(line.text.slice(0, colonPos)));
    const rest = line.text.slice(colonPos + 1).trim();

    if (!rest) {
      const nextIdx = skipBlanks(lines, i + 1);
      if (nextIdx >= lines.length) {
        obj[key] = null;
        i = nextIdx;
      } else if (lines[nextIdx].indent > mapIndent) {
        const nested = parseNode(lines, nextIdx, lines[nextIdx].indent);
        obj[key] = nested.value;
        i = nested.nextIndex;
      } else if (
        lines[nextIdx].indent === mapIndent &&
        (lines[nextIdx].text === "-" || lines[nextIdx].text.startsWith("- "))
      ) {
        // PyYAML often aligns list dashes at the same indent as the parent key
        const seq = parseSequence(lines, nextIdx, mapIndent);
        obj[key] = seq.value;
        i = seq.nextIndex;
      } else {
        obj[key] = null;
        i = nextIdx;
      }
      continue;
    }

    if (/^[|>][+-]?$/.test(rest)) {
      const block = parseBlockScalar(lines, i + 1, mapIndent, rest);
      obj[key] = block.value;
      i = block.nextIndex;
      continue;
    }

    obj[key] = parseScalar(rest);
    i += 1;
  }

  return { value: obj, nextIndex: i };
}

export function parseYaml(source: string): unknown {
  const trimmed = source.replace(/^\uFEFF/, "").trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed);
    } catch {
      // Fall through to YAML parser
    }
  }
  const lines = tokenizeYamlLines(source);
  return parseNode(lines, 0, 0).value;
}

function formatYamlKey(key: string): string {
  if (/^[A-Za-z0-9_.-]+$/.test(key)) {
    return key;
  }
  return JSON.stringify(key);
}

function serializeYamlValue(value: unknown, indent: number): string {
  const pad = " ".repeat(indent);
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "boolean" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    if (value.includes("\n")) {
      const hasTrailingNewline = value.endsWith("\n");
      const trimmedEnd = hasTrailingNewline ? value.slice(0, -1) : value;
      const header = hasTrailingNewline ? "|" : "|-";
      const lines = trimmedEnd.split("\n").map((line) => `${" ".repeat(indent + 2)}${line}`);
      return `${header}\n${lines.join("\n")}`;
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return value
      .map((item) => {
        if (item && typeof item === "object" && !Array.isArray(item)) {
          const entries = Object.entries(item as Record<string, unknown>);
          if (entries.length === 0) return `${pad}- {}`;
          const [firstKey, firstVal] = entries[0];
          const firstRendered = serializeYamlValue(firstVal, indent + 2);
          const firstLine =
            typeof firstVal === "object" && firstVal !== null && ((Array.isArray(firstVal) && firstVal.length > 0) || (!Array.isArray(firstVal) && Object.keys(firstVal).length > 0))
              ? `${pad}- ${formatYamlKey(firstKey)}:\n${firstRendered}`
              : `${pad}- ${formatYamlKey(firstKey)}: ${firstRendered}`;
          const restLines = entries.slice(1).map(([k, v]) => {
            const subPad = " ".repeat(indent + 2);
            const rendered = serializeYamlValue(v, indent + 4);
            const isMultilineContainer =
              (typeof v === "object" && v !== null && ((Array.isArray(v) && v.length > 0) || (!Array.isArray(v) && Object.keys(v).length > 0))) ||
              (typeof v === "string" && v.includes("\n"));
            if (typeof v === "string" && v.includes("\n")) {
              const block = serializeYamlValue(v, indent + 2);
              return `${subPad}${formatYamlKey(k)}: ${block}`;
            }
            return isMultilineContainer
              ? `${subPad}${formatYamlKey(k)}:\n${rendered}`
              : `${subPad}${formatYamlKey(k)}: ${rendered}`;
          });
          return [firstLine, ...restLines].join("\n");
        }
        return `${pad}- ${serializeYamlValue(item, indent + 2)}`;
      })
      .join("\n");
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "{}";
    return entries
      .map(([k, v]) => {
        if (typeof v === "string" && v.includes("\n")) {
          return `${pad}${formatYamlKey(k)}: ${serializeYamlValue(v, indent)}`;
        }
        const rendered = serializeYamlValue(v, indent + 2);
        const isMultilineContainer =
          typeof v === "object" &&
          v !== null &&
          ((Array.isArray(v) && v.length > 0) || (!Array.isArray(v) && Object.keys(v).length > 0));
        return isMultilineContainer
          ? `${pad}${formatYamlKey(k)}:\n${rendered}`
          : `${pad}${formatYamlKey(k)}: ${rendered}`;
      })
      .join("\n");
  }
  return JSON.stringify(String(value));
}

export function stringifyCharacterYaml(characters: Array<Record<string, unknown>>): string {
  return `${serializeYamlValue(characters, 0)}\n`;
}
