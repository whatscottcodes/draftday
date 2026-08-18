"use client";

import { useEffect, useState } from "react";
import { apiJsonRetry, connectDraftSocket } from "@/lib/api";
import type { DraftState } from "@/lib/types";

export function useDraftState(token: string) {
  const [state, setState] = useState<DraftState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ws: WebSocket;
    let closed = false;

    apiJsonRetry<DraftState>(`/api/draft/${token}/display`)
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));

    const openSocket = () => {
      ws = connectDraftSocket(
        token,
        (s) => {
          setState(s);
          setError(null);
        },
        setConnected,
      );
    };
    openSocket();

    const retry = setInterval(() => {
      if (!closed && ws.readyState === WebSocket.CLOSED) {
        openSocket();
      }
    }, 3000);

    return () => {
      closed = true;
      clearInterval(retry);
      ws?.close();
    };
  }, [token]);

  return { state, connected, error };
}