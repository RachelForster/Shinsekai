export function stripHtmlFallback(value: string) {
  let output = "";
  let inTag = false;
  for (const char of Array.from(value ?? "")) {
    if (char === "<") {
      inTag = true;
      continue;
    }
    if (char === ">") {
      inTag = false;
      continue;
    }
    if (!inTag) {
      output += char;
    }
  }
  return output;
}

export function parseHtmlFragment(value: string) {
  if (typeof document === "undefined" || typeof DOMParser === "undefined") {
    return null;
  }
  const parsed = new DOMParser().parseFromString(value, "text/html");
  const fragment = document.createDocumentFragment();
  parsed.body.childNodes.forEach((node) => {
    fragment.append(document.importNode(node, true));
  });
  return fragment;
}
