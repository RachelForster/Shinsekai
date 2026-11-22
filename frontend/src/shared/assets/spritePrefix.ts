const RESERVED_PREFIXES = new Set(["__self__"]);
const INVALID_EFFECT_NAME_PATTERN = /[\\/:*?"<>|\u0000-\u001f]/;

export function suggestUniqueSpritePrefix(
  name: string,
  existingPrefixes: Iterable<string>,
  fallbackBase: "char" | "bg",
): string {
  const used = new Set(RESERVED_PREFIXES);
  for (const prefix of existingPrefixes) {
    const normalized = prefix.trim().toLowerCase();
    if (normalized) {
      used.add(normalized);
    }
  }

  const asciiSlug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");

  if (asciiSlug && !RESERVED_PREFIXES.has(asciiSlug)) {
    if (!used.has(asciiSlug)) {
      return asciiSlug;
    }
    let suffix = 2;
    while (used.has(`${asciiSlug}_${suffix}`)) {
      suffix += 1;
    }
    return `${asciiSlug}_${suffix}`;
  }

  let index = 1;
  while (used.has(`${fallbackBase}_${index}`)) {
    index += 1;
  }
  return `${fallbackBase}_${index}`;
}

export function isValidEffectStorageName(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed || trimmed === "." || trimmed === "..") {
    return false;
  }
  if (trimmed.endsWith(".") || INVALID_EFFECT_NAME_PATTERN.test(trimmed)) {
    return false;
  }
  return !trimmed.includes("..");
}
