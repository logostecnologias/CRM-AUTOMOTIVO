import { useEffect, useRef } from "react";
import api from "@/lib/api";
import { playNotificationSound } from "@/lib/notification-sound";

// Polls for new incoming messages regardless of which page is open,
// as long as the tenant shell (AppShell) stays mounted.
export function useUnreadNotifier(enabled) {
  const prevUnreadRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;
    prevUnreadRef.current = null;

    const check = () => {
      api.get("/atendimento/unread-count").then((r) => {
        const totalUnread = r.data.total || 0;
        if (prevUnreadRef.current !== null && totalUnread > prevUnreadRef.current) {
          playNotificationSound();
        }
        prevUnreadRef.current = totalUnread;
      }).catch(() => {});
    };

    check();
    const t = setInterval(check, 3000);
    return () => clearInterval(t);
  }, [enabled]);
}
