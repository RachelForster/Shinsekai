import "./PathDisplay.css";

interface PathDisplayProps {
  className?: string;
  path?: string;
}

function splitPath(path: string) {
  // A POSIX absolute path may contain a literal backslash in its leaf. Treat
  // backslash as a separator only for Windows/UNC/portable path spellings.
  const match =
    path.startsWith("/") && !path.startsWith("//") ? path.match(/^(.*\/)([^/]*)$/) : path.match(/^(.*[\\/])([^\\/]*)$/);
  if (!match) {
    return { name: path, prefix: "" };
  }
  return { name: match[2] || path, prefix: match[1] || "" };
}

export function PathDisplay({ className = "", path = "" }: PathDisplayProps) {
  const { name, prefix } = splitPath(path);

  return (
    <span
      className={["path-display", className].filter(Boolean).join(" ")}
      data-has-prefix={Boolean(prefix)}
      title={path}
    >
      {prefix ? <span className="path-display__prefix">{prefix}</span> : null}
      <span className="path-display__name">{name}</span>
    </span>
  );
}
