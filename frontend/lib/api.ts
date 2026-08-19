import type { DraftState } from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ADMIN_PASSCODE_KEY = "draftnight_admin_passcode";

export function getAdminPasscode(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(ADMIN_PASSCODE_KEY) ?? "";
}

export function setAdminPasscode(passcode: string): void {
  window.sessionStorage.setItem(ADMIN_PASSCODE_KEY, passcode);
}

export function clearAdminPasscode(): void {
  window.sessionStorage.removeItem(ADMIN_PASSCODE_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function wsUrl(token: string): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/api/draft/${token}/ws`;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const passcode = getAdminPasscode();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(passcode ? { "X-Admin-Passcode": passcode } : {}),
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
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

export async function apiJsonRetry<T>(
  path: string,
  attempts = 4,
  delayMs = 5000,
  init?: RequestInit,
): Promise<T> {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await apiJson<T>(path, init);
    } catch (e) {
      if (attempt === attempts) throw e;
      await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  throw new Error("unreachable");
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