export function baseName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function extractTagContent(line: string) {
  const fullWidth = line.indexOf("：");
  const ascii = line.indexOf(":");
  const index = fullWidth >= 0 && ascii >= 0 ? Math.min(fullWidth, ascii) : Math.max(fullWidth, ascii);
  return index >= 0 ? line.slice(index + 1).trim() : line.trim();
}

export function tagContents(block: string, count: number) {
  const lines = block.split(/\r?\n/).filter(Boolean);
  return Array.from({ length: count }, (_, index) => extractTagContent(lines[index] ?? ""));
}

export function numberedTags(prefix: string, tags: string[]) {
  return tags.map((tag, index) => `${prefix} ${index + 1}：${tag}`).join("\n") + (tags.length ? "\n" : "");
}

export function removeTagRows(block: string, count: number, indexes: number[], prefix: string) {
  const removed = new Set(indexes.filter((index) => index >= 0 && index < count));
  return numberedTags(
    prefix,
    tagContents(block, count).filter((_, index) => !removed.has(index)),
  );
}
