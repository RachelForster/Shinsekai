import { useEffect, useRef, useState } from "react";
import { MonitorPlay, QrCode, Square } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import {
  chatQueryKey,
  conversationsQueryKey,
  getChatSnapshot,
  getCurrentConversation,
} from "../../entities/chat/repository";
import { showChatSurface } from "../../shared/desktop/chatWindow";
import { useI18n } from "../../shared/i18n";
import { Button, Dialog } from "../../shared/ui";
import { closeChatRuntime } from "../chat-startup/runtimeState";
import type { useChatLaunchGuard } from "../chat-startup/useChatLaunchGuard";
import { MobileAccessDialog } from "../mobile-access/MobileAccessDialog";

const POLL_INTERVAL_MS = 1200;

export function ActiveConversationPanel({
  guard,
}: {
  guard: Pick<
    ReturnType<typeof useChatLaunchGuard>,
    "runtimeState" | "runtimeClosing" | "updateRuntimeStatusFromSnapshot"
  >;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { runtimeState, runtimeClosing, updateRuntimeStatusFromSnapshot } = guard;
  const active = runtimeState === "running" || runtimeClosing;
  const snapshot = useQuery({
    queryKey: chatQueryKey,
    queryFn: getChatSnapshot,
    enabled: active,
    refetchInterval: active ? POLL_INTERVAL_MS : false,
    staleTime: 0,
  });
  const current = useQuery({
    queryKey: [...chatQueryKey, "current-conversation", snapshot.data?.sessionId],
    queryFn: getCurrentConversation,
    enabled: active && snapshot.isSuccess,
    refetchInterval: active ? POLL_INTERVAL_MS : false,
    staleTime: 0,
  });
  const [qrOpen, setQrOpen] = useState(false);
  const [confirmation, setConfirmation] = useState<{ sessionId?: string } | null>(null);
  const [ending, setEnding] = useState(false);
  const endingRef = useRef(false);
  const [error, setError] = useState("");
  const [endError, setEndError] = useState("");
  const busy = ending || runtimeClosing;

  useEffect(() => {
    setQrOpen(false);
    setConfirmation(null);
    setError("");
    setEndError("");
  }, [active, snapshot.data?.sessionId]);

  const openLocalChat = async () => {
    setError("");
    try {
      const fresh = await getChatSnapshot();
      await updateRuntimeStatusFromSnapshot(fresh);
      if (fresh.chatProcessRunning && !fresh.chatRuntimeClosing) {
        setQrOpen(false);
        await showChatSurface({ navigate, snapshot: fresh });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const endChat = async () => {
    if (!confirmation || endingRef.current || runtimeClosing) return;
    endingRef.current = true;
    setEnding(true);
    setEndError("");
    try {
      const fresh = await getChatSnapshot();
      if (fresh.sessionId !== confirmation.sessionId) {
        throw new Error(t("conversation.activeChanged"));
      }
      const closed = await closeChatRuntime();
      await client.cancelQueries({ queryKey: chatQueryKey, exact: true });
      client.setQueryData(chatQueryKey, closed);
      await updateRuntimeStatusFromSnapshot(closed);
      setQrOpen(false);
      setConfirmation(null);
      await client.invalidateQueries({ queryKey: conversationsQueryKey });
    } catch (reason) {
      setEndError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      endingRef.current = false;
      setEnding(false);
    }
  };

  if (!active) return null;

  return (
    <section className="conversation-library__active" aria-label={t("conversation.activeTitle")}>
      <div className="conversation-library__active-info">
        <h2>{t("conversation.activeName", { title: current.data?.title || t("conversation.untitled") })}</h2>
        <p role="status">{t(busy ? "conversation.ending" : "conversation.activeHint")}</p>
      </div>
      <div className="conversation-library__active-actions">
        {snapshot.data?.mobileAccess?.enabled && (
          <Button
            disabled={busy}
            icon={<QrCode aria-hidden className="button__icon" />}
            onClick={() => setQrOpen(true)}
          >
            {t("conversation.showQr")}
          </Button>
        )}
        <Button
          disabled={busy || !snapshot.isSuccess}
          icon={<MonitorPlay aria-hidden className="button__icon" />}
          onClick={() => void openLocalChat()}
        >
          {t("conversation.openChat")}
        </Button>
        <Button
          disabled={busy || !snapshot.isSuccess}
          icon={<Square aria-hidden className="button__icon" />}
          onClick={() => {
            setEndError("");
            setConfirmation({ sessionId: snapshot.data?.sessionId });
          }}
          variant="danger"
        >
          {t(busy ? "conversation.ending" : "conversation.endChat")}
        </Button>
      </div>
      {(snapshot.isError || current.isError || error) && (
        <p role="alert">{error || snapshot.error?.message || current.error?.message}</p>
      )}
      {snapshot.isError && <Button onClick={() => void snapshot.refetch()}>{t("common.refresh")}</Button>}
      <MobileAccessDialog
        info={qrOpen && !busy ? (snapshot.data?.mobileAccess ?? null) : null}
        onClose={() => setQrOpen(false)}
        onOpenLocalChat={openLocalChat}
      />
      <Dialog
        open={Boolean(confirmation)}
        title={t("conversation.endChat")}
        closeLabel={t("common.close")}
        dismissible={!busy}
        onClose={() => {
          if (!busy) setConfirmation(null);
        }}
        footer={
          <>
            <Button disabled={busy} onClick={() => setConfirmation(null)}>
              {t("common.cancel")}
            </Button>
            <Button disabled={busy} loading={ending} variant="danger" onClick={() => void endChat()}>
              {t(busy ? "conversation.ending" : endError ? "conversation.retryEnd" : "conversation.endChat")}
            </Button>
          </>
        }
      >
        <p>{t(snapshot.data?.mobileAccess?.enabled ? "conversation.endMobileConfirm" : "conversation.endConfirm")}</p>
        {endError && <p role="alert">{endError}</p>}
      </Dialog>
    </section>
  );
}
