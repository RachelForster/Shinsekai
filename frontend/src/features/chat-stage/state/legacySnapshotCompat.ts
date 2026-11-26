/**
 * Legacy fallback for historical snapshots saved before explicit
 * `systemMessageText`, `statusMessage`, or `isSystemDialog` metadata existed.
 * New backend/preview code must emit structured fields instead of adding rules here.
 */
const LEGACY_SYSTEM_SNAPSHOT_PREFIX =
  /^(已跳过|已选择|选择：|历史|浏览器预览历史|语音识别|正在请求|聊天会话|您的消息已提交|进程已经|当前聊天会话|实时聊天会话)/;

export function isLegacySystemSnapshotText(value: string) {
  const text = value.trim();
  if (!text) {
    return false;
  }
  return LEGACY_SYSTEM_SNAPSHOT_PREFIX.test(text);
}
