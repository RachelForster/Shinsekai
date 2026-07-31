const PATH_CONTROL_CHARACTER = /[\u0000-\u001f\u007f\ud800-\udfff]/u;
const PORTABLE_COMPONENT_FORBIDDEN_CHARACTER = /[<>:"/\\|?*]/u;
const WINDOWS_RESERVED_DEVICE_NAME = /^(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM(?:[1-9¹²³])|LPT(?:[1-9¹²³]))$/iu;
const UTF8_ENCODER = new TextEncoder();
const MAX_PORTABLE_COMPONENT_UTF8_BYTES = 255;

/**
 * Match the host path contract for one portable file or directory name.
 *
 * Files selected on one platform can later be consumed by another platform
 * (or by the Python side of the desktop bridge).  Accepting a component here
 * that the host rejects produces a path that is displayable but unreachable.
 */
export function isPortablePathComponent(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !value ||
    value !== value.trim() ||
    value === "." ||
    value === ".." ||
    PATH_CONTROL_CHARACTER.test(value) ||
    PORTABLE_COMPONENT_FORBIDDEN_CHARACTER.test(value) ||
    value.endsWith(" ") ||
    value.endsWith(".") ||
    UTF8_ENCODER.encode(value).byteLength > MAX_PORTABLE_COMPONENT_UTF8_BYTES
  ) {
    return false;
  }
  return !WINDOWS_RESERVED_DEVICE_NAME.test(value.split(".", 1)[0]);
}

export function containsPathControlCharacter(value: string) {
  return PATH_CONTROL_CHARACTER.test(value);
}

/**
 * Normalize separators only where backslash is part of the shared portable
 * path syntax.
 *
 * A backslash inside a POSIX absolute path is a literal filename character.
 * Rewriting it would collapse two different host files (`/tmp/a\b` and
 * `/tmp/a/b`) into one frontend identity. Windows, UNC, and project-relative
 * values continue to use slash-normalized comparison keys.
 */
export function normalizePathSeparatorsForIdentity(value: string) {
  return value.startsWith("/") && !value.startsWith("//") ? value : value.replaceAll("\\", "/");
}
