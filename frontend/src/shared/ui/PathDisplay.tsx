interface PathDisplayProps {
  className?: string;
  path?: string;
}

function splitPath(path: string) {
  const match = path.match(/^(.*[\\/])([^\\/]*)$/);
  if (!match) {
    return { name: path, prefix: "" };
  }
  return { name: match[2] || path, prefix: match[1] || "" };
}

export function PathDisplay({ className = "", path = "" }: PathDisplayProps) {
  const trimmed = path.trim();
  const { name, prefix } = splitPath(trimmed);

  return (
    <span className={["path-display", className].filter(Boolean).join(" ")} title={trimmed}>
      {prefix ? <span className="path-display__prefix">{prefix}</span> : null}
      <span className="path-display__name">{name}</span>
    </span>
  );
}
