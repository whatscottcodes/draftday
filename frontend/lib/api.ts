import type { DraftState } from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function wsUrl(token: string): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/api/draft/${token}/ws`;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail.length) {
        detail = body.detail
          .map((d: { msg?: string }) => d.msg ?? JSON.stringify(d))
          .join("; ");
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function connectDraftSocket(
  token: string,
  onState: (state: DraftState) => void,
  onStatus?: (connected: boolean) => void,
): WebSocket {
  const ws = new WebSocket(wsUrl(token));
  ws.onopen = () => onStatus?.(true);
  ws.onclose = () => onStatus?.(false);
  ws.onerror = () => onStatus?.(false);
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data as string);
      if (msg.type === "state") onState(msg.data as DraftState);
    } catch {
      /* ignore */
    }
  };
  return ws;
}