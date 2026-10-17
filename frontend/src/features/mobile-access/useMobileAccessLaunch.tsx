import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { showChatSurface } from "../../shared/desktop/chatWindow";
import type { ChatSnapshot, MobileAccessInfo } from "../../shared/platform/types";
import { MobileAccessDialog } from "./MobileAccessDialog";

/** Reuse the workspace's QR/local-window handoff for every chat launch entry. */
export function useMobileAccessLaunch() {
  const navigate = useNavigate();
  const [info, setInfo] = useState<MobileAccessInfo | null>(null);
  const openChat = async (snapshot: ChatSnapshot) => {
    if (snapshot.mobileAccess) setInfo(snapshot.mobileAccess);
    else await showChatSurface({ navigate, snapshot });
  };
  const dialog = info ? (
    <MobileAccessDialog
      info={info}
      onClose={() => setInfo(null)}
      onOpenLocalChat={() => {
        setInfo(null);
        return showChatSurface({ navigate, snapshot: { runtimeMode: "react", wsUrl: info.websocketUrl } });
      }}
    />
  ) : null;
  return { openChat, dialog };
}
