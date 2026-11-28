import { BookOpen, MessageCircle, ScrollText } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import type { ConversationSummary } from "../../shared/platform/types";
import "./ConversationTypeBadge.css";

export function ConversationTypeBadge({ kind }: { kind: ConversationSummary["kind"] }) {
  const { t } = useI18n();
  const Icon = kind === "story" ? BookOpen : kind === "novel" ? ScrollText : MessageCircle;
  const labelKey =
    kind === "story" ? "conversation.story" : kind === "novel" ? "conversation.novel" : "conversation.normal";
  return (
    <span className={`conversation-type-badge conversation-type-badge--${kind}`}>
      <Icon size={13} aria-hidden="true" />
      {t(labelKey)}
    </span>
  );
}
