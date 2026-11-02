import { BookOpen, MessageCircle } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import type { ConversationSummary } from "../../shared/platform/types";
import "./ConversationTypeBadge.css";

export function ConversationTypeBadge({ kind }: { kind: ConversationSummary["kind"] }) {
  const { t } = useI18n();
  const Icon = kind === "story" ? BookOpen : MessageCircle;
  return (
    <span className={`conversation-type-badge conversation-type-badge--${kind}`}>
      <Icon size={13} aria-hidden="true" />
      {t(kind === "story" ? "conversation.story" : "conversation.normal")}
    </span>
  );
}
