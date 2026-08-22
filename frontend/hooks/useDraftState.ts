"use client";

import { useEffect, useState } from "react";
import { apiJsonRetry, connectDraftSocket } from "@/lib/api";
import type { DraftState } from "@/lib/types";

export function useDraftState(token: string) {
  const [state, setState] = useState<DraftState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;

    const fetchDisplay = () => {
      apiJsonRetry<DraftState>(`/api/draft/${token}/display`)
        .then((s) => {
          if (!closed) {
            setState(s);
            setError(null);
          }
        })
        .catch((e) => {
          if (!closed) setError(e instanceof Error ? e.message : "Failed to load");
        });
    };

    fetchDisplay();

    const openSocket = () => {
      ws = connectDraftSocket(
        token,
        (s) => {
          if (!closed) {
            setState(s);
            setError(null);
          }
        },
        setConnected,
      );
    };
    openSocket();

    const interval = setInterval(() => {
      if (closed) return;
      if (!ws || ws.readyState === WebSocket.CLOSED) {
        openSocket();
      }
      fetchDisplay();
    }, 4000);

    return () => {
      closed = true;
      clearInterval(interval);
      ws?.close();
    };
  }, [token]);

  return { state, connected, error };
}