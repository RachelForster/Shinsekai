/** Use local creation time when a new chat has no user-supplied title. */
export function resolveConversationTitle(title?: string, createdAt = new Date()): string {
  if (title?.trim()) return title.trim();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${createdAt.getFullYear()}-${pad(createdAt.getMonth() + 1)}-${pad(createdAt.getDate())} ${pad(createdAt.getHours())}:${pad(createdAt.getMinutes())}:${pad(createdAt.getSeconds())}`;
}
